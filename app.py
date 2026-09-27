"""Jornada40 — MVP (Streamlit, multipage). Run: streamlit run app.py

v3 flow (docs/CHANGELOG_v2.md #5): left menu = Reiniciar App · Inicio · Diagnóstico · Generar Programación.
Inicio holds the demo, the template download, the uploads, the chain's opening schedule and the scenario.
Solver core lives in the `jornada40` package and does not depend on this UI.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from jornada40 import config
from jornada40.ingest.flat import SCHEDULE_COLS, load_chain
from jornada40.optimizer import OptimizerSettings
from jornada40.pipeline import assess_store, assessment_row, demo_chain, run_store, shift_rows

ROOT = Path(__file__).parent
TPL = ROOT / "data" / "templates_app"
CUR, PRO, NEED, UP, DOWN = "#9A3B3B", "#1F6F5C", "#1B2421", "#C0873F", "#1F6F5C"
DAYS_ES = {"Mon": "Lun", "Tue": "Mar", "Wed": "Mié", "Thu": "Jue", "Fri": "Vie", "Sat": "Sáb", "Sun": "Dom"}
WD_ES = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
WEEKDAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
SCENARIOS = {"40 Horas": 2030, "42 Horas": 2029, "44 Horas": 2028, "46 Horas": 2027}
POLICIES = {"5": "Semana de 5 días", "6": "Semana de 6 días"}
OFFPEAK_PENALTY_MXN = 150.0  # off-peak shortfall weight (D31); not user-facing since v2
SOLVER_TIME_LIMIT_S = 10.0  # safety cap; stores solve to optimality in < 1 s
HOURS = [f"{h:02d}:{m:02d}" for h in range(5, 24) for m in (0, 30)] + ["24:00"]  # 05:00 … 24:00
OPEN, CLOSED = "Abierta", "Cerrada"

st.set_page_config(page_title="Jornada40 · Programación semanal", page_icon="📅", layout="wide")
ss = st.session_state

# Streamlit drops widget state on a page change; re-assigning the keys keeps the user's choices
# (bug found in v2, CHANGELOG #4). The scenario lives in ss["scenario"], shared by two selectors.
_PERSIST = ["scenario"] + [f"h_{k}_{d}" for d in range(7) for k in ("state", "open", "close")]
for _k in _PERSIST:
    if _k in ss:
        ss[_k] = ss[_k]
ss.setdefault("scenario", "40 Horas")
scen = ss["scenario"]
year = SCENARIOS[scen]
wmax, cap = config.weekly_max_ordinary(year), config.overtime_cap_2x(year)
if ss.get("year_key") != year:  # scenario changed -> recompute diagnosis and results
    for _k in ("assess", "results"):
        ss.pop(_k, None)
    ss["year_key"] = year


# ---------------------------------------------------------------- helpers
def mxn(x) -> str:
    return f"${float(x):,.0f}"


def md_mxn(x) -> str:  # "$" starts LaTeX in st.markdown
    return mxn(x).replace("$", "\\$")


def signed_mxn(x) -> str:
    return f"{'-' if float(x) < 0 else '+'}${abs(float(x)):,.0f}"


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


def dia(ts) -> str:
    s = ts.strftime("%a %d")
    return DAYS_ES.get(s[:3], s[:3]) + s[3:]


def templates_zip() -> bytes:
    """v3: only the filled example (50 stores x 80 employees) + instructions, no empty template."""
    return zip_bytes({
        "programacion_actual.csv": (TPL / "ejemplo_programacion_actual_50_tiendas.csv").read_bytes(),
        "requerimiento.csv": (TPL / "ejemplo_requerimiento_50_tiendas.csv").read_bytes(),
        "LEEME.txt": (
            "Plantillas de ejemplo llenas: 50 tiendas x 80 empleados. Sustituye las filas por tus datos.\n\n"
            "programacion_actual.csv (obligatorio): una fila por turno trabajado en la semana.\n"
            "  tienda, empleado, puesto, salario_diario (MXN), en_piso (1 atiende piso / 0 administrativo),\n"
            "  dias_descanso (p. ej. sab|dom), zona (general|zlfn), fecha (AAAA-MM-DD), entrada, salida (HH:MM).\n"
            "  Si la salida es menor que la entrada, el turno termina al día siguiente.\n\n"
            "requerimiento.csv (opcional pero recomendado): número de EMPLEADOS (no clientes) que necesitas en\n"
            "  piso en cada hora de cada día. Columnas: tienda, fecha, hora (0-23), personas_requeridas,\n"
            "  es_pico (1/0, opcional). Con este archivo detectamos horas con gente de más o de menos y los\n"
            "  turnos siguen tu demanda; sin él se conserva tu cobertura actual hora por hora.\n\n"
            "El horario de apertura y cierre y los días que la tienda cierra se capturan en la app (Inicio).\n"
        ).encode()})


@st.cache_resource(show_spinner=False)
def _demo_inputs():
    return demo_chain()


def reset_downstream() -> None:
    for k in ("assess", "results"):
        ss.pop(k, None)


def load_demo() -> None:
    ss["inputs"], ss["source"], ss["msgs"], ss["req_source"] = _demo_inputs(), "demo sintética", ([], []), "uploaded"
    reset_downstream()


def ensure_assessed() -> None:
    if "inputs" in ss and "assess" not in ss:
        with st.spinner(f"Evaluando {len(ss['inputs'])} tiendas…"):
            ss["assess"] = {k: assess_store(v, year) for k, v in ss["inputs"].items()}


def status_line() -> None:
    if "inputs" in ss:
        wk = next(iter(ss["inputs"].values())).week_start
        n_emp = sum(len(v.employees) for v in ss["inputs"].values())
        st.caption(f"{len(ss['inputs'])} tiendas · {n_emp:,} empleados · semana del {wk:%d/%m/%Y} · "
                   f"fuente: {ss['source']} · escenario: {scen}")


def _on_scenario(key: str) -> None:
    ss["scenario"] = ss[key]


def scenario_selector(key: str, label: str) -> None:
    """Same scenario in Inicio and Diagnóstico (ss['scenario'] is the single source of truth)."""
    st.selectbox(label, list(SCENARIOS), index=list(SCENARIOS).index(ss["scenario"]), key=key,
                 on_change=_on_scenario, args=(key,))
    st.caption(f"Tope: **{wmax} h/semana**. Horas {wmax + 1}–{wmax + cap}: pago **doble**. "
               f"Horas {wmax + cap + 1}–{wmax + cap + 4}: pago **triple**. Más allá: prohibido.")


def run_generation() -> None:
    inputs, assess = ss["inputs"], ss["assess"]
    bar = st.progress(0.0, text="Optimizando…")
    out, total, i = {}, 2 * len(inputs), 0
    for pol, label in POLICIES.items():
        settings = OptimizerSettings(year=year, time_limit_s=SOLVER_TIME_LIMIT_S,
                                     offpeak_under_penalty_mxn=OFFPEAK_PENALTY_MXN, allow_sixth_day=False,
                                     week_policy=pol)
        out[pol] = {}
        for k, v in inputs.items():
            out[pol][k] = run_store(v, year, settings, current=assess[k])
            i += 1
            bar.progress(i / total, text=f"{label} · tienda {k}")
    ss["results"] = out


# ---------------------------------------------------------------- sidebar: menu only (v3)
def sidebar() -> None:
    with st.sidebar:
        if st.button("Reiniciar App", icon=":material/restart_alt:", width="stretch"):
            for k in list(ss.keys()):
                del ss[k]
            st.switch_page(P_HOME)
        st.divider()
        st.page_link(P_HOME, label="Inicio", icon=":material/home:")
        st.page_link(P_DIAG, label="Diagnóstico", icon=":material/monitoring:")
        st.page_link(P_NEW, label="Generar Programación", icon=":material/event_available:")


# ================================================================ INICIO
def schedule_form() -> tuple[dict[int, tuple[str, str] | None], list[str]]:
    """One opening schedule for the whole chain. Every day must be filled: open with hours, or closed."""
    st.markdown("**Agrega aquí el horario de tu operación y los días de trabajo / descanso**")
    st.caption("Un solo horario para todas las tiendas. **Cerrada** = nadie se programa ese día.")
    hours, issues = {}, []
    h = st.columns([1.2, 1.4, 1.2, 1.2])
    for col, t in zip(h, ("Día", "Tienda", "Apertura", "Cierre")):
        col.markdown(f"<small><b>{t}</b></small>", unsafe_allow_html=True)
    for d, name in enumerate(WEEKDAY_NAMES):
        c = st.columns([1.2, 1.4, 1.2, 1.2], vertical_alignment="center")
        c[0].markdown(name)
        state = c[1].selectbox(name, [OPEN, CLOSED], index=None, placeholder="Selecciona…",
                               key=f"h_state_{d}", label_visibility="collapsed")
        disabled = state != OPEN
        o = c[2].selectbox(f"{name} apertura", HOURS[:-1], index=None,
                           placeholder="—" if disabled else "Apertura",
                           key=f"h_open_{d}", label_visibility="collapsed", disabled=disabled)
        cl = c[3].selectbox(f"{name} cierre", HOURS[1:], index=None,
                            placeholder="—" if disabled else "Cierre",
                            key=f"h_close_{d}", label_visibility="collapsed", disabled=disabled)
        if state is None:
            issues.append(f"{name}: indica si la tienda abre o está cerrada.")
        elif state == CLOSED:
            hours[d] = None
        elif o is None or cl is None:
            issues.append(f"{name}: selecciona hora de apertura y de cierre.")
        elif cl <= o:
            issues.append(f"{name}: el cierre debe ser después de la apertura.")
        else:
            hours[d] = (o, cl)
    if not issues and sum(v is not None for v in hours.values()) < 5:
        issues.append("La tienda debe abrir al menos 5 días a la semana (turnos de tiempo completo).")
    return hours, issues


def page_home() -> None:
    st.title("Jornada40")
    st.markdown("#### Esta herramienta te ayuda a que tu operación actual respete el tope legal de horas "
                "trabajadas por empleado a la semana conforme a lo establecido por la Ley Federal del Trabajo.")
    if "inputs" in ss:
        with st.container(border=True):
            status_line()
            nxt = P_NEW if "results" in ss else P_DIAG
            if st.button(f"Continuar → {'Generar Programación' if nxt is P_NEW else 'Diagnóstico'}"):
                st.switch_page(nxt)

    with st.container(border=True):
        st.markdown("**⚡ Pruébalo ahora**")
        st.markdown("Este demo cargará data sintética de 50 tiendas con 80 FTEs (empleados) cada una.")
        if st.button("Probar demo", type="primary"):
            load_demo()
            st.switch_page(P_DIAG)

    st.header("¿Quieres usar tus datos?")
    st.markdown("Para usar tus datos por favor descarga nuestras plantillas, llénalas con tu programación real y "
                "agrega horario/días de descanso.")
    st.info("**Importante:** la plantilla de requerimiento es opcional, sin embargo es aconsejable llenarla pues "
            "contiene información relevante sobre el número de empleados mínimos necesarios por hora para cubrir "
            "las necesidades de tu operación.")
    st.download_button("Descargar plantilla", templates_zip(), "jornada40_plantillas_ejemplo_50_tiendas.zip",
                       type="primary", icon=":material/download:")
    st.caption("La plantilla viene llena con el ejemplo de 50 tiendas × 80 empleados; sustituye las filas por tus datos.")

    st.markdown("**Nota:** cuando tengas las plantillas llenas con tus datos, súbelas aquí:")
    f_sched = st.file_uploader("1. programacion_actual.csv", type="csv", key="up_sched")
    f_req = st.file_uploader("2. requerimiento.csv (opcional)", type="csv", key="up_req")

    day_hours, issues = schedule_form()

    st.markdown("**Por último selecciona el escenario con las horas tope que debería cumplir tu operación semanal "
                "aquí:**")
    scenario_selector("scen_home", "Horas tope por semana")

    missing = ([] if f_sched is not None else ["Sube programacion_actual.csv."]) + issues
    if missing and (f_sched is not None or any(k in ss and ss[k] for k in (f"h_state_{d}" for d in range(7)))):
        st.warning("Para continuar falta:\n\n" + "\n".join(f"- {m}" for m in missing))
    if st.button("Analizar mis archivos", type="primary", disabled=bool(missing)):
        with st.spinner("Leyendo archivos…"):
            ch = load_chain(f_sched, f_req, year, day_hours=day_hours)
        ss["msgs"] = (ch.errors, ch.warnings)
        if ch.stores and not ch.errors:
            ss["inputs"], ss["source"], ss["req_source"] = ch.stores, "archivos del usuario", ch.requirement_source
            reset_downstream()
            st.switch_page(P_DIAG)
    errs, warns = ss.get("msgs", ([], []))
    for e in errs:
        st.error(e)
    if warns:
        with st.expander(f"{len(warns)} avisos"):
            for w in warns:
                st.write("•", w)


# ================================================================ DIAGNÓSTICO
def coverage_gap_chart(cov: pd.DataFrame, day_label: str) -> alt.VConcatChart:
    """Requerido vs Actual for one day: thick baseline, shaded gap (red = people above requirement,
    orange = below) and a delta bar chart underneath (Actual − Requerido). CHANGELOG #7."""
    d = cov.copy()
    d["delta"] = d["have"] - d["need"]
    d["hi"] = d[["have", "need"]].max(axis=1)
    d["over"] = d["have"].where(d["have"] > d["need"], d["need"])
    d["under"] = d["have"].where(d["have"] < d["need"], d["need"])
    x = alt.X("t:T", title=None, axis=alt.Axis(format="%H:%M"))
    over = alt.Chart(d).mark_area(interpolate="step-after", opacity=0.35, color=CUR).encode(
        x=x, y=alt.Y("need:Q"), y2="over:Q")
    under = alt.Chart(d).mark_area(interpolate="step-after", opacity=0.45, color=UP).encode(
        x=x, y=alt.Y("need:Q"), y2="under:Q")
    peaks = alt.Chart(d[d["is_peak"] == 1]).mark_rect(opacity=0.10, color=NEED).encode(
        x="t:T", x2="t_end:T").transform_calculate(t_end="datum.t + 30*60*1000")
    lines = alt.Chart(d.melt(id_vars=["t"], value_vars=["need", "have"], var_name="serie", value_name="personas")
                      .replace({"need": "Requerido", "have": "Actual"})).mark_line(interpolate="step-after").encode(
        x=x, y=alt.Y("personas:Q", title="Personas en piso"),
        color=alt.Color("serie:N", title=None, legend=alt.Legend(orient="top"),
                        scale=alt.Scale(domain=["Requerido", "Actual"], range=[NEED, CUR])),
        strokeWidth=alt.condition(alt.datum.serie == "Requerido", alt.value(4), alt.value(2)),
        tooltip=[alt.Tooltip("t:T", format="%H:%M", title="Hora"), alt.Tooltip("serie:N", title=""),
                 alt.Tooltip("personas:Q", title="Personas")])
    top = (peaks + over + under + lines).properties(height=300, title=f"{day_label}: requerido vs actual")
    bars = alt.Chart(d).mark_bar(size=9).encode(
        x=x, y=alt.Y("delta:Q", title="Actual − Requerido"),
        color=alt.condition(alt.datum.delta > 0, alt.value(CUR), alt.value(UP)),
        tooltip=[alt.Tooltip("t:T", format="%H:%M", title="Hora"), alt.Tooltip("delta:Q", title="Diferencia")]
    ).properties(height=120)
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=NEED).encode(y="y:Q")
    return alt.vconcat(top, bars + zero).resolve_scale(x="shared")


def page_diag() -> None:
    st.title("Diagnóstico de la programación actual")
    if "inputs" not in ss:
        st.info("Primero carga datos: prueba la demo o sube tus archivos en Inicio.")
        st.page_link(P_HOME, label="Ir a Inicio", icon=":material/home:")
        return
    scenario_selector("scen_diag", "Escenario de horas tope por semana")
    ensure_assessed()
    inputs, assess = ss["inputs"], ss["assess"]
    status_line()
    has_req = ss.get("req_source") != "current coverage"
    diag = pd.DataFrame([assessment_row(k, inputs[k], assess[k], year) for k in inputs])
    diag["empleados_requeridos"] = [int(inputs[k].requirement["required_headcount"].max()) if has_req else None
                                    for k in inputs]

    st.markdown("**De acuerdo a la información compartida tu operación cuenta con:**")
    a, b, c = st.columns(3)
    a.metric("Tiendas", f"{len(diag):,}")
    b.metric("Empleados", f"{diag.empleados.sum():,}")
    c.metric("Costo laboral semanal total", mxn(diag.costo_semanal.sum()))

    st.markdown("**En tu programación actual se detectaron:**")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Horas dobles pagadas", f"{diag.horas_dobles.sum():,.0f} h",
              help=f"Desde la hora {wmax + 1} de la semana o por encima del máximo diario de la jornada.")
    k2.metric("Horas triples pagadas", f"{diag.horas_triples.sum():,.0f} h")
    k3.metric("Prima dominical pagada", mxn(diag.prima_dominical.sum()))
    extras = diag.primas_total.sum()
    k4.metric("Costo de horas extra y primas", mxn(extras),
              f"{extras / diag.costo_semanal.sum() * 100:.1f} % del costo laboral semanal", delta_color="off")
    st.caption(f"Incluye horas dobles y triples ({md_mxn(diag.costo_horas_dobles.sum() + diag.costo_horas_triples.sum())}), "
               f"descansos trabajados pagados triple ({diag.descansos_trabajados.sum():,} · "
               f"{md_mxn(diag.costo_descansos.sum())}), feriados ({md_mxn(diag.costo_feriados.sum())}) y prima "
               "dominical. Una hora se paga doble cuando rebasa el tope semanal o el máximo diario de su jornada "
               "(8 h diurna, 7.5 h mixta, 7 h nocturna — arts. 60–61, 66–68 LFT).")

    st.markdown("**Cobertura frente a lo requerido (personal en piso):**")
    if has_req:
        over_h, under_h, peak_h = diag.sobredotacion_h.sum(), diag.subdotacion_h.sum(), diag.faltante_pico_h.sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Sobredotación (gente de más)", f"{over_h:,.0f} persona-h",
                  f"≈ {over_h / 40:,.0f} empleados de tiempo completo", delta_color="off",
                  help="Horas en que hubo más personas en piso que las requeridas, sumadas en la semana.")
        c2.metric("Subdotación (gente de menos)", f"{under_h:,.0f} persona-h",
                  f"≈ {under_h / 40:,.0f} empleados de tiempo completo", delta_color="off",
                  help="Horas en que hubo menos personas en piso que las requeridas, sumadas en la semana.")
        c3.metric("Subdotación en horas pico", f"{peak_h:,.0f} persona-h",
                  f"≈ {peak_h / 40:,.0f} empleados de tiempo completo", delta_color="off")
        st.caption("Equivalencia: persona-horas de la semana ÷ 40 h = empleados de tiempo completo. Puedes tener gente "
                   "de más a media tarde y gente de menos en los picos al mismo tiempo; la gráfica de abajo lo muestra "
                   "hora por hora.")
    else:
        st.caption("Sin requerimiento.csv no se puede medir sobre- ni subdotación: el requerido es tu cobertura actual.")

    st.subheader("Top 15 de sucursales con más gasto en horas extra y primas")
    top = diag.nlargest(15, "primas_total").melt(id_vars="tienda", value_vars=[
        "costo_horas_dobles", "costo_horas_triples", "costo_descansos", "costo_feriados", "prima_dominical"],
        var_name="concepto", value_name="MXN")
    names = {"costo_horas_dobles": "Horas dobles", "costo_horas_triples": "Horas triples",
             "costo_descansos": "Descanso trabajado", "costo_feriados": "Feriado", "prima_dominical": "Prima dominical"}
    top["concepto"] = top["concepto"].map(names)
    order = diag.nlargest(15, "primas_total")["tienda"].astype(str).tolist()
    top["tienda"] = top["tienda"].astype(str)
    st.altair_chart(alt.Chart(top).mark_bar().encode(
        y=alt.Y("tienda:N", sort=order, title="Tienda"), x=alt.X("MXN:Q", stack=True, title="MXN por semana"),
        color=alt.Color("concepto:N", title=None, legend=alt.Legend(orient="bottom", columns=3, labelLimit=200),
                        scale=alt.Scale(domain=list(names.values()),
                                        range=[CUR, "#C98B6B", "#6B4E71", "#8A8F4A", "#9AA5A0"])),
        # explicit tooltip: otherwise Streamlit shows its internal "_concepto_sort_index" field (v3 note)
        tooltip=[alt.Tooltip("tienda:N", title="Tienda"), alt.Tooltip("concepto:N", title="Concepto"),
                 alt.Tooltip("MXN:Q", format="$,.0f")]),
        width="stretch")

    st.subheader("Detalle por tienda")
    diag["sobredotacion_fte"] = (diag.sobredotacion_h / 40).round(1)
    diag["subdotacion_fte"] = (diag.subdotacion_h / 40).round(1)
    show = diag[["tienda", "empleados", "horas_dobles", "costo_horas_dobles", "horas_triples", "descansos_trabajados",
                 "prima_dominical", "primas_total", "costo_semanal", "sobredotacion_h", "sobredotacion_fte",
                 "subdotacion_h", "subdotacion_fte", "faltante_pico_h", "empleados_requeridos",
                 "violaciones"]].rename(columns={
                     "primas_total": "costo_extras_y_primas", "faltante_pico_h": "Personal_faltante_en_pico",
                     "violaciones": "Violaciones_LFT"})
    if not has_req:
        show = show.drop(columns=["sobredotacion_h", "sobredotacion_fte", "subdotacion_h", "subdotacion_fte"])
    st.dataframe(show.sort_values("costo_extras_y_primas", ascending=False), hide_index=True, width="stretch",
                 height=320, column_config={
                     **{c: st.column_config.NumberColumn(format="$%,.0f") for c in
                        ("costo_horas_dobles", "prima_dominical", "costo_extras_y_primas", "costo_semanal")},
                     "sobredotacion_fte": st.column_config.NumberColumn(
                         help="Sobredotación en empleados de tiempo completo: persona-horas ÷ 40."),
                     "subdotacion_fte": st.column_config.NumberColumn(
                         help="Subdotación en empleados de tiempo completo: persona-horas ÷ 40."),
                     "Personal_faltante_en_pico": st.column_config.NumberColumn(
                         help="Persona-horas que faltaron en horas pico: empleados requeridos menos empleados en "
                              "piso, sumado cada 30 minutos de las horas pico de la semana."),
                     "empleados_requeridos": st.column_config.NumberColumn(
                         help="Máximo de empleados requeridos en una hora de la semana, según requerimiento.csv."),
                     "Violaciones_LFT": st.column_config.NumberColumn(
                         help="Casos que rompen la LFT: más de 4 días con horas extra, más de 12 h seguidas, "
                              "7 días seguidos, menores fuera de norma.")})
    if not has_req:
        st.caption("Sin requerimiento.csv: *Personal_faltante_en_pico* y *empleados_requeridos* no se pueden medir.")

    st.subheader("Cobertura: requerido vs actual")
    sid_c = st.selectbox("Tienda", list(inputs), key="cov_store")
    cov = assess[sid_c].coverage.copy()
    cov["dia"] = cov["t"].map(dia)
    day = st.radio("Día", list(dict.fromkeys(cov["dia"])), horizontal=True, key="cov_day")
    dd = cov[cov["dia"] == day]
    st.altair_chart(coverage_gap_chart(dd, day), width="stretch")
    over_h = float((dd["delta"] if "delta" in dd else (dd["have"] - dd["need"])).clip(lower=0).sum() * 0.5)
    under_h = float((dd["need"] - dd["have"]).clip(lower=0).sum() * 0.5)
    st.caption(f"Rojo = gente de más sobre lo requerido ({over_h:,.0f} persona-h ese día); naranja = gente de menos "
               f"({under_h:,.0f} persona-h). Línea gruesa = requerido. Franjas grises = horas pico. Intervalos de 30 min."
               + (" Sin requerimiento.csv el requerido es tu cobertura actual, por lo que no hay brecha."
                  if not has_req else ""))

    st.subheader("Detalle por empleado")
    sid = st.selectbox("Tienda", list(inputs), key="diag_store")
    emp = inputs[sid].employees.set_index("employee_id")
    rows = [(w.employee_id, emp.loc[w.employee_id, "role"], w.worked_h + w.restday_h, w.ot_2x_h, w.ot_3x_h,
             w.restdays_worked, float(emp.loc[w.employee_id, "daily_salary"]) / 8 * (2 * w.ot_2x_h + 3 * w.ot_3x_h))
            for w in assess[sid].report.weeks]
    det = pd.DataFrame(rows, columns=["empleado", "puesto", "horas_trabajadas", "horas_dobles", "horas_triples",
                                      "descansos_trabajados", "costo_extra"]).sort_values("costo_extra", ascending=False)
    st.dataframe(det, hide_index=True, width="stretch",
                 column_config={"costo_extra": st.column_config.NumberColumn(format="$%,.2f")})
    st.download_button("Descargar diagnóstico (CSV)", show.to_csv(index=False).encode(), "diagnostico_actual.csv")

    st.divider()
    cta_l, cta_r = st.columns([2, 3])
    shift6 = min(config.weekly_max_ordinary(year) * 60 // 6 // 30 * 30 / 60, 8)
    cta_r.markdown("Optimiza cada tienda con **CP-SAT** (Google OR-Tools) en dos escenarios para que compares: "
                   f"**semana de 5 días** (turnos de 8 h, 2 descansos) y **semana de 6 días** (turnos de "
                   f"{shift6:g} h, 1 descanso — art. 69). Ambos respetan el tope semanal.")
    if cta_l.button("Generar nueva programación", type="primary", width="stretch"):
        run_generation()
        st.switch_page(P_NEW)


# ================================================================ GENERAR PROGRAMACIÓN
def valid(res: dict) -> dict:
    """Stores where the week type applies (e.g. 6-day weeks need >= 6 open days)."""
    return {k: r for k, r in res.items() if r.opt.status != "NO_APLICA"}


def waterfall(cur, pro, title: str) -> alt.Chart:
    """Current cost -> proposed cost, step by step (base salaries are equal on both sides)."""
    steps = [("Horas extra", float(pro.overtime_2x + pro.overtime_3x - cur.overtime_2x - cur.overtime_3x)),
             ("Descansos", float(pro.restday_extra - cur.restday_extra)),
             ("Feriados", float(pro.feriado_extra - cur.feriado_extra)),
             ("Prima dom.", float(pro.prima_dominical - cur.prima_dominical))]
    rows, level = [("Actual", 0.0, float(cur.total_cash), "total")], float(cur.total_cash)
    for name, delta in steps:
        rows.append((name, level, level + delta, "sube" if delta > 0 else "baja"))
        level += delta
    rows.append(("Propuesto", 0.0, float(pro.total_cash), "total"))
    df = pd.DataFrame(rows, columns=["paso", "y0", "y1", "tipo"])
    df["delta"] = df.y1 - df.y0
    df["lbl"] = [f"${v:,.0f}" if t == "total" else f"{'+' if d > 0 else '−'}${abs(d):,.0f}"
                 for v, d, t in zip(df.y1, df.delta, df.tipo)]
    lo = min(df.loc[df.tipo != "total", ["y0", "y1"]].min().min(), float(pro.total_cash)) * 0.97
    df["y0"] = df.y0.clip(lower=lo)
    base = alt.Chart(df).encode(x=alt.X("paso:N", sort=None, title=None,
                                        axis=alt.Axis(labelAngle=0, labelLimit=120, labelOverlap=False,
                                                      labelFontSize=11)))
    bars = base.mark_bar(size=46).encode(
        y=alt.Y("y0:Q", title="MXN por semana", scale=alt.Scale(domain=[lo, float(cur.total_cash) * 1.01])),
        y2="y1:Q",
        color=alt.Color("tipo:N", legend=None, scale=alt.Scale(domain=["total", "baja", "sube"],
                                                                range=["#6E7C77", DOWN, UP])),
        tooltip=["paso", alt.Tooltip("delta:Q", format=",.0f", title="MXN")])
    df["top"] = df[["y0", "y1"]].max(axis=1)
    labels = alt.Chart(df).mark_text(dy=-8, fontSize=12).encode(
        x=alt.X("paso:N", sort=None), y="top:Q", text="lbl:N")
    return (bars + labels).properties(title=title, height=320)


def page_new() -> None:
    st.title("Generar programación")
    if "results" not in ss:
        if "inputs" not in ss:
            st.info("Primero carga datos: prueba la demo o sube tus archivos en Inicio.")
            st.page_link(P_HOME, label="Ir a Inicio", icon=":material/home:")
            return
        status_line()
        st.info("Aún no has generado la nueva programación para estos datos.")
        if st.button("Generar nueva programación", type="primary"):
            ensure_assessed()
            run_generation()
            st.rerun()
        return
    status_line()
    # --- week type (small dropdown, no comparison table — CHANGELOG #8)
    ss.setdefault("week_type", POLICIES["5"])
    choice = st.selectbox("Tipo de semana", list(POLICIES.values()),
                          index=list(POLICIES.values()).index(ss["week_type"]), key="week_type_sel",
                          help="Semana de 5 días: turnos de 8 h y 2 descansos. Semana de 6 días: turnos más cortos y "
                               "1 descanso (art. 69). Cambia la opción para ver cómo cambia la propuesta.")
    ss["week_type"] = choice
    pol = [p for p, lbl in POLICIES.items() if lbl == choice][0]
    results = valid(ss["results"][pol])
    if not results:
        st.warning("Este tipo de semana no aplica con el horario de tu operación (la tienda abre menos días de los "
                   "que requiere). Elige la otra opción.")
        return
    summ = pd.DataFrame([r.summary() for r in results.values()])
    summ["store_id"] = list(results)

    # --- Programación actual vs propuesta (chain)
    st.subheader("Programación actual vs propuesta")
    def tot(side: str, attr: str) -> float:
        return sum(float(getattr(getattr(r, side).cost, attr)) for r in results.values())
    def viol(side: str) -> int:
        return sum(1 for r in results.values() for f in getattr(r, side).report.findings if f.kind == "VIOLATION")
    rows = [
        ("Costo laboral total (MXN/semana)", tot("current", "total_cash"), tot("proposed", "total_cash"), "mxn"),
        ("Costo de horas extra y primas (MXN/semana)", tot("current", "premiums"), tot("proposed", "premiums"), "mxn"),
        ("Horas dobles y triples pagadas", tot("current", "overtime_hours"), tot("proposed", "overtime_hours"), "h"),
        (f"Violaciones a la LFT (escenario {scen})", viol("current"), viol("proposed"), "n"),
        ("Sobredotación (persona-h)", tot("current", "overstaff_person_h"), tot("proposed", "overstaff_person_h"), "h"),
        ("Sobredotación (empleados de tiempo completo)", tot("current", "overstaff_person_h") / 40,
         tot("proposed", "overstaff_person_h") / 40, "fte"),
        ("Subdotación (persona-h)", tot("current", "understaff_person_h"), tot("proposed", "understaff_person_h"), "h"),
        ("Subdotación (empleados de tiempo completo)", tot("current", "understaff_person_h") / 40,
         tot("proposed", "understaff_person_h") / 40, "fte"),
        ("Subdotación en horas pico (persona-h)", tot("current", "understaff_peak_person_h"),
         tot("proposed", "understaff_peak_person_h"), "h"),
    ]
    def f(v, kind):
        return {"mxn": f"${v:,.0f}", "h": f"{v:,.0f} h", "n": f"{v:,.0f}", "fte": f"{v:,.1f}"}[kind]
    def fd(a, b, kind):
        d = b - a
        pct = f" ({d / a * 100:+.1f} %)" if kind == "mxn" and a else ""
        return {"mxn": f"{'-' if d < 0 else '+'}${abs(d):,.0f}", "h": f"{d:+,.0f} h", "n": f"{d:+,.0f}",
                "fte": f"{d:+,.1f}"}[kind] + pct
    cmp_df = pd.DataFrame([(n, f(a, k), f(b, k), fd(a, b, k)) for n, a, b, k in rows],
                          columns=["Concepto", "Actual", "Propuesta", "Diferencia"]).set_index("Concepto")
    st.dataframe(cmp_df, width="stretch")
    st.caption(f"{len(results)} tiendas · semana del {next(iter(results.values())).inp.week_start:%d/%m/%Y} · "
               f"{choice.lower()} · solver: {', '.join(f'{n} {s}' for s, n in summ.solver_status.value_counts().items())}. "
               "Salarios base iguales en ambos lados: la diferencia de costo viene de horas extra y primas. "
               "Empleados de tiempo completo = persona-horas ÷ 40.")

    tbl = summ[["store_id", "employees", "current_total", "proposed_total", "saving_mxn", "saving_pct", "current_ot_h",
                "proposed_ot_h", "current_restday_calls", "current_peak_short_h", "proposed_peak_short_h",
                "solver_status"]]
    tbl.columns = ["tienda", "empleados", "costo_actual", "costo_propuesto", "ahorro", "ahorro_%",
                   "horas_extra_antes", "horas_extra_despues", "descansos_trabajados_antes", "faltante_pico_antes",
                   "faltante_pico_despues", "solver"]
    st.dataframe(tbl, hide_index=True, width="stretch", height=260,
                 column_config={c: st.column_config.NumberColumn(format="$%,.0f")
                                for c in ("costo_actual", "costo_propuesto", "ahorro")})

    wk0 = next(iter(results.values())).inp.week_start
    wk1 = wk0 + pd.Timedelta(days=6)

    def proposed_flat(k, res) -> pd.DataFrame:
        emp = res.inp.employees.set_index("employee_id")
        worked: dict[str, set[int]] = {}
        for s in res.proposed.shifts:
            worked.setdefault(s.employee_id, set()).add(s.day.weekday())
        rows = []
        for s in sorted(res.proposed.shifts, key=lambda s: (s.employee_id, s.start)):
            e = emp.loc[s.employee_id]
            rows.append([k, s.employee_id, e.get("role", ""), float(e["daily_salary"]), int(e.get("is_floor", 1)),
                         "|".join(WD_ES[d] for d in range(7) if d not in worked[s.employee_id]),
                         res.inp.store.get("salary_zone", "general"), s.day.isoformat(), s.start.strftime("%H:%M"),
                         s.end.strftime("%H:%M"), s.jornada_code, wk0.isoformat(), wk1.isoformat()])
        return pd.DataFrame(rows, columns=SCHEDULE_COLS + ["jornada", "semana_inicio", "semana_fin"])

    d1, d2 = st.columns(2)
    d1.download_button(f"Descargar nueva programación — {choice.lower()} · {wk0:%d/%m/%Y} a {wk1:%d/%m/%Y} (CSV)",
                       pd.concat([proposed_flat(k, x) for k, x in results.items()]).to_csv(index=False).encode(),
                       f"nueva_programacion_{pol}dias_{wk0.isoformat()}_a_{wk1.isoformat()}.csv", type="primary",
                       width="stretch")
    d2.download_button("Descargar resumen de ahorro (CSV)", tbl.to_csv(index=False).encode(), "ahorro_por_tienda.csv",
                       width="stretch")

    # ---- drill-down
    st.subheader("Detalle por tienda")
    sid = st.selectbox("Tienda", list(results), key="res_store")
    x = results[sid]
    cur, pro = x.current.cost, x.proposed.cost
    a, b, c, d = st.columns(4)
    a.metric("Ahorro semanal", mxn(x.saving_mxn), f"{x.saving_pct:.1f} %")
    b.metric("Costo propuesto", mxn(pro.total_cash), signed_mxn(-x.saving_mxn) + " vs actual", delta_color="inverse")
    c.metric("Horas extra", f"{pro.overtime_hours:,.0f} h", f"{pro.overtime_hours - cur.overtime_hours:+,.0f} h",
             delta_color="inverse")
    d.metric("Horas sobre lo requerido", f"{pro.overstaff_person_h:,.0f} h", help="Capacidad liberada, no efectivo.",
             delta=f"{pro.overstaff_person_h - cur.overstaff_person_h:+,.0f} h", delta_color="inverse")
    t1, t2, t3 = st.tabs(["Cobertura", "Desglose del ahorro", "Programación propuesta"])
    with t1:
        cc = x.current.coverage[["t", "need", "is_peak", "have"]].rename(columns={"have": "Actual"})
        cc["Propuesta"] = x.proposed.coverage.set_index("t")["have"].reindex(cc["t"]).fillna(0).values
        cc["dia"] = cc["t"].map(dia)
        day = st.radio("Día", list(dict.fromkeys(cc["dia"])), horizontal=True)
        dd = cc[cc["dia"] == day].melt(id_vars=["t", "is_peak"], value_vars=["need", "Actual", "Propuesta"],
                                       var_name="serie", value_name="personas")
        dd["serie"] = dd["serie"].replace({"need": "Requerido"})
        band = alt.Chart(cc[(cc["dia"] == day) & (cc["is_peak"] == 1)]).mark_rect(opacity=0.12, color=NEED).encode(
            x="t:T", x2="t_end:T").transform_calculate(t_end="datum.t + 30*60*1000")
        line = alt.Chart(dd).mark_line(interpolate="step-after", strokeWidth=2.5).encode(
            x=alt.X("t:T", title=None, axis=alt.Axis(format="%H:%M")), y=alt.Y("personas:Q", title="Personas en piso"),
            color=alt.Color("serie:N", title=None, legend=alt.Legend(orient="bottom"),
                            scale=alt.Scale(domain=["Requerido", "Actual", "Propuesta"], range=[NEED, CUR, PRO])),
            strokeDash=alt.condition(alt.datum.serie == "Requerido", alt.value([4, 3]), alt.value([0])))
        st.altair_chart(band + line, width="stretch")
        st.caption("Franjas sombreadas = horas pico (sin subdotación permitida). Intervalos de 30 min.")
    with t2:
        st.altair_chart(waterfall(cur, pro, f"Tienda {sid}"), width="stretch")
    with t3:
        rr = shift_rows(x.proposed.shifts, x.inp.employees)
        rr["turno"] = rr["start_time"] + "–" + rr["end_time"] + " " + rr["jornada_code"]
        rr["dia"] = pd.to_datetime(rr["date"]).map(dia)
        g = rr.pivot_table(index=["employee_id", "role"], columns="dia", values="turno",
                           aggfunc="first").fillna("descanso")
        g = g[[c for c in dict.fromkeys(rr.sort_values("date")["dia"]) if c in g.columns]]
        g["horas"] = rr.groupby(["employee_id", "role"])["hours"].sum()
        st.dataframe(g.reset_index().rename(columns={"employee_id": "empleado", "role": "puesto"}), hide_index=True,
                     width="stretch", height=420)
        st.caption("D = diurna, M = mixta. Semana de 5 días (2 descansos) o de 6 días (1 descanso — art. 69).")


# ================================================================ navigation (menu lives in the sidebar, v3)
P_HOME = st.Page(page_home, title="Inicio", icon=":material/home:", default=True)
P_DIAG = st.Page(page_diag, title="Diagnóstico", icon=":material/monitoring:", url_path="diagnostico")
P_NEW = st.Page(page_new, title="Generar Programación", icon=":material/event_available:",
                url_path="generar-programacion")
nav = st.navigation([P_HOME, P_DIAG, P_NEW], position="hidden")
sidebar()
nav.run()
