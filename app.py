"""Jornada40 — MVP (Streamlit, multipage). Run: streamlit run app.py

Menu (D37): Inicio · Datos · Diagnóstico · Nueva programación — one page per step of the job.
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
from jornada40.checks import presolve_checks
from jornada40.ingest.flat import SCHEDULE_COLS, load_chain
from jornada40.optimizer import OBJECTIVE_COMPONENTS, OptimizerSettings
from jornada40.pipeline import assess_store, assessment_row, demo_chain, run_store, shift_rows

ROOT = Path(__file__).parent
TPL = ROOT / "data" / "templates_app"
CUR, PRO, NEED, UP, DOWN = "#9A3B3B", "#1F6F5C", "#1B2421", "#C0873F", "#1F6F5C"
DAYS_ES = {"Mon": "Lun", "Tue": "Mar", "Wed": "Mié", "Thu": "Jue", "Fri": "Vie", "Sat": "Sáb", "Sun": "Dom"}
WD_ES = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
SCENARIOS = {"Tope de 40 h (reforma completa)": 2030, "Transición — 42 h": 2029, "Transición — 44 h": 2028,
             "Transición — 46 h": 2027}
POLICIES = {"5": "Semana de 5 días", "6": "Semana de 6 días"}

st.set_page_config(page_title="Jornada40 · Programación semanal", page_icon="📅", layout="wide")
ss = st.session_state


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


@st.cache_resource(show_spinner=False)
def _demo_inputs():
    return demo_chain()


def reset_downstream() -> None:
    for k in ("assess", "results"):
        ss.pop(k, None)


def load_demo() -> None:
    ss["inputs"], ss["source"], ss["msgs"] = _demo_inputs(), "demo sintética", ([], [])
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
                   f"fuente: {ss['source']} · reglas: {scen}")


# ---------------------------------------------------------------- sidebar (all pages)
def sidebar() -> None:
    global scen, year, wmax, cap, offpeak, sixth, tlimit
    with st.sidebar:
        st.header("Escenario")
        scen = st.selectbox("Reglas LFT", list(SCENARIOS), index=0,
                            help="El tope semanal define desde qué hora se paga doble.")
        year = SCENARIOS[scen]
        wmax, cap = config.weekly_max_ordinary(year), config.overtime_cap_2x(year)
        st.caption(f"Tope: **{wmax} h/semana**. Horas {wmax + 1}–{wmax + cap}: pago **doble**. "
                   f"Horas {wmax + cap + 1}–{wmax + cap + 4}: pago **triple**. Más allá: prohibido.")
        with st.expander("Parámetros del optimizador"):
            offpeak = st.slider("Penalización por faltante fuera de pico (MXN por persona-hora)", 0, 1000, 150, 10,
                                help="En horas pico el faltante está prácticamente prohibido. Fuera de pico, este "
                                     "valor decide cuándo conviene pagar un 6.º día con horas extra para cubrir un hueco.")
            sixth = st.checkbox("Semana de 5 días: permitir un 6.º día completo como horas extra si hace falta", True)
            tlimit = st.slider("Tiempo máximo del solver por tienda (s)", 2, 30, 10)
        if st.button("Empezar de nuevo", width="stretch"):
            for k in ("inputs", "assess", "results", "source", "msgs"):
                ss.pop(k, None)
            st.switch_page(P_HOME)
    if ss.get("year_key") != year:  # rules changed -> recompute downstream
        reset_downstream()
        ss["year_key"] = year


# ================================================================ INICIO
def page_home() -> None:
    st.title("Jornada40")
    st.markdown("#### Programación semanal que respeta el tope legal de horas y te dice cuánto ahorras.")
    st.markdown("Para cadenas de hasta **50 tiendas**. Detecta las horas que hoy se pagan dobles o triples, "
                "genera una nueva programación con **CP-SAT** y compara el costo en pesos.")
    if "inputs" in ss:
        with st.container(border=True):
            status_line()
            nxt = P_NEW if "results" in ss else P_DIAG
            if st.button(f"Continuar → {nxt.title}", type="primary"):
                st.switch_page(nxt)
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("**⚡ Pruébalo ahora**")
        st.caption("Carga la demo sintética: 50 tiendas × 80 empleados, semana del 28/09/2026.")
        if st.button("Probar con la demo de 50 tiendas", type="primary", width="stretch"):
            load_demo()
            st.switch_page(P_DIAG)
    with c2, st.container(border=True):
        st.markdown("**📄 Usa tus datos**")
        st.caption("Descarga la plantilla CSV, llénala con la programación real y súbela.")
        if st.button("Ir a Datos", width="stretch"):
            st.switch_page(P_DATA)
    st.markdown("##### Cómo funciona")
    a, b, c = st.columns(3)
    for col, n, t, d in ((a, 1, "Datos", "Una fila por turno: tienda, empleado, salario diario, fecha, entrada y "
                          "salida. Requerimiento por hora opcional."),
                         (b, 2, "Diagnóstico", "Horas pagadas dobles y triples, descansos trabajados, prima "
                          "dominical, violaciones LFT y chequeo de capacidad."),
                         (c, 3, "Nueva programación", "CP-SAT optimiza cada tienda con semana de 5 y de 6 días; "
                          "comparas ahorro y cobertura y descargas la que elijas.")):
        with col, st.container(border=True):
            st.markdown(f"**{n} · {t}**")
            st.caption(d)


# ================================================================ DATOS
def page_data() -> None:
    st.title("Datos")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**1. Descarga la plantilla**, llénala con la programación real de la semana (una fila por "
                    "turno) y súbela. El requerimiento por hora es opcional pero recomendado.")
        st.download_button("Descargar plantillas CSV", zip_bytes({
            "plantilla_programacion_actual.csv": (TPL / "plantilla_programacion_actual.csv").read_bytes(),
            "plantilla_requerimiento.csv": (TPL / "plantilla_requerimiento.csv").read_bytes(),
            "LEEME.txt": ("programacion_actual.csv: una fila por turno trabajado.\n"
                          "  tienda, empleado, puesto, salario_diario (MXN), en_piso (1 atiende piso / 0 administrativo),\n"
                          "  dias_descanso (p. ej. sab|dom), zona (general|zlfn), fecha (AAAA-MM-DD), entrada, salida (HH:MM).\n"
                          "  Si la salida es menor que la entrada, el turno termina al día siguiente.\n"
                          "requerimiento.csv (opcional): tienda, fecha, hora (0-23), personas_requeridas, es_pico (1/0).\n"
                          "  Sin este archivo se conserva la cobertura actual de cada tienda hora por hora.\n").encode()}),
            "jornada40_plantillas.zip", width="stretch")
        st.download_button("Descargar ejemplo lleno (50 tiendas × 80 empleados)", zip_bytes({
            "programacion_actual.csv": (TPL / "ejemplo_programacion_actual_50_tiendas.csv").read_bytes(),
            "requerimiento.csv": (TPL / "ejemplo_requerimiento_50_tiendas.csv").read_bytes()}),
            "jornada40_ejemplo_50_tiendas.zip", width="stretch")
        st.caption("Columnas: " + ", ".join(SCHEDULE_COLS) + ". También acepta encabezados en inglés y `;`.")
    with c2:
        f_sched = st.file_uploader("2. programacion_actual.csv", type="csv")
        f_req = st.file_uploader("requerimiento.csv (opcional)", type="csv")
        b1, b2 = st.columns(2)
        if b1.button("Analizar mis archivos", type="primary", disabled=f_sched is None, width="stretch"):
            with st.spinner("Leyendo archivos…"):
                ch = load_chain(f_sched, f_req, year)
            ss["msgs"] = (ch.errors, ch.warnings)
            if ch.stores and not ch.errors:
                ss["inputs"], ss["source"] = ch.stores, "archivos del usuario"
                reset_downstream()
                st.switch_page(P_DIAG)
        if b2.button("Usar demo de 50 tiendas", width="stretch"):
            load_demo()
            st.switch_page(P_DIAG)
    errs, warns = ss.get("msgs", ([], []))
    for e in errs:
        st.error(e)
    if warns:
        with st.expander(f"{len(warns)} avisos"):
            for w in warns:
                st.write("•", w)
    if "inputs" in ss:
        status_line()


# ================================================================ DIAGNÓSTICO
def page_diag() -> None:
    st.title("Diagnóstico de la programación actual")
    if "inputs" not in ss:
        st.info("Primero carga datos.")
        st.page_link(P_DATA, label="Ir a Datos", icon=":material/upload_file:")
        return
    ensure_assessed()
    inputs, assess = ss["inputs"], ss["assess"]
    status_line()
    diag = pd.DataFrame([assessment_row(k, inputs[k], assess[k], year) for k in inputs])
    extra = diag.costo_horas_dobles.sum() + diag.costo_horas_triples.sum()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Horas pagadas dobles", f"{diag.horas_dobles.sum():,.0f} h",
              help=f"Desde la hora {wmax + 1} de la semana o por encima del máximo diario de la jornada.")
    k2.metric("Costo de horas dobles y triples", mxn(extra))
    k3.metric("Descansos trabajados (triple)", f"{diag.descansos_trabajados.sum():,}")
    k4.metric("Costo laboral semanal", mxn(diag.costo_semanal.sum()))
    st.markdown(f"Horas triples: **{diag.horas_triples.sum():,.0f} h** · costo de descansos trabajados: "
                f"**{md_mxn(diag.costo_descansos.sum())}** · prima dominical: **{md_mxn(diag.prima_dominical.sum())}** · "
                f"extras y primas = **{diag.primas_total.sum() / diag.costo_semanal.sum() * 100:.1f} %** del costo laboral.")
    st.caption("Una hora se paga **doble** cuando rebasa el tope semanal o el máximo diario de su tipo de jornada "
               "(8 h diurna, 7.5 h mixta, 7 h nocturna — arts. 60–61, 66–68 LFT). Trabajar el día de descanso o un "
               "feriado se paga triple (arts. 73 y 75). Tarifa por hora = salario diario ÷ 8.")

    l, r = st.columns([3, 2])
    with l:
        show = diag[["tienda", "empleados", "horas_dobles", "costo_horas_dobles", "horas_triples",
                     "descansos_trabajados", "prima_dominical", "primas_total", "costo_semanal", "faltante_pico_h",
                     "violaciones"]]
        st.dataframe(show.sort_values("primas_total", ascending=False), hide_index=True, width="stretch", height=320,
                     column_config={c: st.column_config.NumberColumn(format="$%,.0f") for c in
                                    ("costo_horas_dobles", "prima_dominical", "primas_total", "costo_semanal")})
    with r:
        top = diag.nlargest(15, "primas_total").melt(id_vars="tienda", value_vars=[
            "costo_horas_dobles", "costo_horas_triples", "costo_descansos", "costo_feriados", "prima_dominical"],
            var_name="concepto", value_name="MXN")
        names = {"costo_horas_dobles": "Horas dobles", "costo_horas_triples": "Horas triples",
                 "costo_descansos": "Descanso trabajado", "costo_feriados": "Feriado", "prima_dominical": "Prima dominical"}
        top["concepto"] = top["concepto"].map(names)
        st.altair_chart(alt.Chart(top).mark_bar().encode(
            y=alt.Y("tienda:N", sort="-x", title="Tienda"), x=alt.X("sum(MXN):Q", title="Extras y primas, MXN/semana"),
            color=alt.Color("concepto:N", title=None, legend=alt.Legend(orient="bottom", columns=2, labelLimit=200),
                            scale=alt.Scale(domain=list(names.values()),
                                            range=[CUR, "#C98B6B", "#6B4E71", "#8A8F4A", "#9AA5A0"]))),
            width="stretch")
        st.caption("15 tiendas con más costo en extras.")

    with st.expander("Detalle por empleado"):
        sid = st.selectbox("Tienda", list(inputs), key="diag_store")
        emp = inputs[sid].employees.set_index("employee_id")
        rows = [(w.employee_id, emp.loc[w.employee_id, "role"], w.worked_h + w.restday_h, w.ot_2x_h, w.ot_3x_h,
                 w.restdays_worked,
                 float(emp.loc[w.employee_id, "daily_salary"]) / 8 * (2 * w.ot_2x_h + 3 * w.ot_3x_h))
                for w in assess[sid].report.weeks]
        det = pd.DataFrame(rows, columns=["empleado", "puesto", "horas_trabajadas", "horas_dobles", "horas_triples",
                                          "descansos_trabajados", "costo_extra"]).sort_values("costo_extra",
                                                                                              ascending=False)
        st.dataframe(det, hide_index=True, width="stretch",
                     column_config={"costo_extra": st.column_config.NumberColumn(format="$%,.2f")})
    st.download_button("Descargar diagnóstico (CSV)", diag.to_csv(index=False).encode(), "diagnostico_actual.csv")

    # ---- pre-solve checks (D37)
    st.subheader("Chequeo de capacidad antes de optimizar")
    chk = []
    for k, v in inputs.items():
        for c in presolve_checks(v.requirement, v.week_start, len(v.floor_ids), year):
            chk.append({"tienda": k, "semana": POLICIES[c.policy], "estado": c.severity, "mensaje": c.message,
                        "persona_dias_min": c.need_person_days, "persona_dias_disp": c.capacity_person_days})
    chk = pd.DataFrame(chk)
    icon = {"error": "🔴 faltante en pico garantizado", "warning": "🟡 faltante fuera de pico / capacidad justa",
            "ok": "🟢 sin problemas detectados"}
    summary = chk.groupby(["semana", "estado"]).size().unstack(fill_value=0).reindex(
        columns=["error", "warning", "ok"], fill_value=0).rename(columns=icon)
    st.dataframe(summary, width="stretch")
    st.caption("Cota rápida: puntos de demanda separados por al menos un turno no los puede cubrir la misma persona, "
               "así que cada día necesita la suma de esas demandas en personas distintas. 🔴 es un problema seguro "
               "con ese tipo de semana; 🟡/🟢 no garantizan cobertura perfecta (el optimizador da el resultado exacto).")
    bad = chk[chk.estado == "error"]
    if len(bad):
        with st.expander(f"{len(bad)} tienda-escenarios con faltante en pico garantizado"):
            st.dataframe(bad[["tienda", "semana", "persona_dias_min", "persona_dias_disp", "mensaje"]],
                         hide_index=True, width="stretch")

    # ---- CTA
    st.divider()
    cta_l, cta_r = st.columns([2, 3])
    shift6 = config.weekly_max_ordinary(year) * 60 // 6 // 30 * 30 / 60
    cta_r.markdown("Optimiza cada tienda con **CP-SAT** (Google OR-Tools) en dos escenarios para que compares: "
                   f"**semana de 5 días** (turnos de 8 h, 2 descansos) y **semana de 6 días** (turnos de "
                   f"{min(shift6, 8):g} h, 1 descanso — art. 69). Ambos respetan el tope semanal.")
    if cta_l.button("Generar nueva programación", type="primary", width="stretch"):
        bar = st.progress(0.0, text="Optimizando…")
        out, total, i = {}, 2 * len(inputs), 0
        for pol, label in POLICIES.items():
            settings = OptimizerSettings(year=year, time_limit_s=float(tlimit),
                                         offpeak_under_penalty_mxn=float(offpeak), allow_sixth_day=sixth,
                                         week_policy=pol)
            out[pol] = {}
            for k, v in inputs.items():
                out[pol][k] = run_store(v, year, settings, current=assess[k])
                i += 1
                bar.progress(i / total, text=f"{label} · tienda {k}")
        ss["results"] = out
        st.switch_page(P_NEW)


# ================================================================ NUEVA PROGRAMACIÓN
def chain_kpis(res: dict) -> dict:
    s_ = pd.DataFrame([r.summary() for r in res.values()])
    c_ = lambda a: sum(float(getattr(r.proposed.cost, a)) for r in res.values())  # noqa: E731
    cur_total = s_.current_total.sum()
    return {"Ahorro semanal (MXN)": cur_total - s_.proposed_total.sum(),
            "Ahorro %": (cur_total - s_.proposed_total.sum()) / cur_total * 100,
            "Tiendas con ahorro ≥ 8 % sin faltante en pico": int(((s_.saving_pct >= 8) &
                                                                  (s_.proposed_peak_short_h == 0)).sum()),
            "Faltante en horas pico (persona-h)": c_("understaff_peak_person_h"),
            "Faltante total (persona-h)": c_("understaff_person_h"),
            "Horas sobre lo requerido": c_("overstaff_person_h"),
            "Horas extra": c_("overtime_hours"),
            "Prima dominical (MXN)": c_("prima_dominical")}


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
    st.title("Nueva programación y ahorro")
    if "results" not in ss:
        st.info("Genera la nueva programación desde el diagnóstico.")
        st.page_link(P_DIAG, label="Ir a Diagnóstico", icon=":material/monitoring:")
        return
    status_line()
    cmp = pd.DataFrame({POLICIES[p]: chain_kpis(ss["results"][p]) for p in POLICIES})
    cmp.loc["Descansos por persona"] = ["2", "1"]
    fmt = {"Ahorro semanal (MXN)": "${:,.0f}", "Ahorro %": "{:.1f} %", "Prima dominical (MXN)": "${:,.0f}"}
    cmp_show = cmp.apply(lambda row: [fmt.get(row.name, "{:,.0f}").format(v) if isinstance(v, (int, float)) else v
                                      for v in row], axis=1, result_type="broadcast")
    st.subheader("Compara: semana de 5 días vs 6 días")
    st.dataframe(cmp_show, width="stretch")
    a5, a6 = cmp.loc["Ahorro %"]
    s5, s6 = cmp.loc["Faltante total (persona-h)"]
    st.caption(f"**Trade-off:** la semana de 6 días pone más personas por día con turnos más cortos → "
               f"{'menos' if s6 < s5 else 'más'} faltante ({s5:,.0f} → {s6:,.0f} persona-h) pero más empleados "
               f"trabajan domingo (prima dominical). Ahorro en efectivo: {a5:.1f} % vs {a6:.1f} %. "
               "Ambas opciones son legales; la LFT solo exige 1 descanso por cada 6 días trabajados (art. 69).")
    goal = cmp.loc["Tiendas con ahorro ≥ 8 % sin faltante en pico"]
    default = POLICIES["5"] if goal[POLICIES["5"]] >= goal[POLICIES["6"]] else POLICIES["6"]
    choice = st.radio("Ver detalle y descargar:", list(POLICIES.values()), horizontal=True,
                      index=list(POLICIES.values()).index(default))
    pol = [p for p, lbl in POLICIES.items() if lbl == choice][0]
    results = ss["results"][pol]
    summ = pd.DataFrame([r.summary() for r in results.values()])
    summ["store_id"] = list(results)
    tc, tp = summ.current_total.sum(), summ.proposed_total.sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ahorro semanal de la cadena", mxn(tc - tp), f"{(tc - tp) / tc * 100:.1f} % del costo actual")
    k2.metric("Anualizado indicativo (×52)", mxn((tc - tp) * 52))
    k3.metric("Horas dobles y triples", f"{summ.proposed_ot_h.sum():,.0f} h",
              f"{summ.proposed_ot_h.sum() - summ.current_ot_h.sum():+,.0f} h", delta_color="inverse")
    k4.metric("Faltante en horas pico", f"{summ.proposed_peak_short_h.sum():,.0f} persona-h",
              f"{summ.proposed_peak_short_h.sum() - summ.current_peak_short_h.sum():+,.0f}", delta_color="inverse")
    ok = int(((summ.saving_pct >= 8) & (summ.proposed_peak_short_h == 0)).sum())
    (st.success if ok == len(summ) else st.warning)(
        f"{ok} de {len(summ)} tiendas ahorran ≥ 8 % sin subdotación en horas pico · "
        f"violaciones LFT: {summ.current_violations.sum():,} → {summ.proposed_violations.sum():,} · "
        f"solver: {', '.join(f'{n} {s}' for s, n in summ.solver_status.value_counts().items())}")

    # ---- cost breakdown (D37)
    class _Sum:  # chain totals with the same attributes as CostSummary
        def __init__(self, side: str):
            for a in ("total_cash", "overtime_2x", "overtime_3x", "restday_extra", "feriado_extra",
                      "prima_dominical"):
                setattr(self, a, sum(getattr(getattr(r, side).cost, a) for r in results.values()))
    l, r = st.columns([3, 2])
    with l:
        st.altair_chart(waterfall(_Sum("current"), _Sum("proposed"), "De dónde sale el ahorro (cadena)"),
                        width="stretch")
        st.caption("Salarios base iguales en ambos lados: el ahorro viene de las primas y extras que se dejan de pagar. "
                   "Verde = baja el costo, ámbar = sube.")
    with r:
        st.altair_chart(alt.Chart(summ).mark_bar(color=PRO).encode(
            x=alt.X("store_id:N", title="Tienda", sort=None, axis=alt.Axis(labels=False, ticks=False)),
            y=alt.Y("saving_pct:Q", title="Ahorro % por tienda"),
            tooltip=["store_id", "saving_pct", "saving_mxn"]) + alt.Chart(pd.DataFrame({"y": [8]})).mark_rule(
            strokeDash=[4, 3], color=NEED).encode(y="y:Q"), width="stretch")
        st.caption("Línea punteada = meta de 8 %.")
    with st.expander("Cómo decidió el optimizador (función objetivo)"):
        comp = pd.DataFrame([{OBJECTIVE_COMPONENTS[k]: v for k, v in x.opt.components.items()}
                             for x in results.values()]).sum()
        comp = comp[comp.abs() > 0.5].sort_values(ascending=False).rename("MXN/semana (cadena)")
        st.dataframe(comp.to_frame(), width="stretch", column_config={
            "MXN/semana (cadena)": st.column_config.NumberColumn(format="$%,.0f")})
        st.caption("CP-SAT minimiza la suma de estos términos (en centavos). Las líneas de *penalización* no son "
                   "dinero pagado: son pesos que le dicen al solver qué evitar (el faltante en pico cuesta tanto que "
                   "nunca conviene). Los montos de prima y horas extra usan el salario promedio; el costo exacto se "
                   "recalcula empleado por empleado en la tabla y la cascada.")

    tbl = summ[["store_id", "employees", "current_total", "proposed_total", "saving_mxn", "saving_pct", "current_ot_h",
                "proposed_ot_h", "current_restday_calls", "current_peak_short_h", "proposed_peak_short_h",
                "solver_status"]]
    tbl.columns = ["tienda", "empleados", "costo_actual", "costo_propuesto", "ahorro", "ahorro_%",
                   "horas_extra_antes", "horas_extra_despues", "descansos_trabajados_antes", "faltante_pico_antes",
                   "faltante_pico_despues", "solver"]
    st.dataframe(tbl, hide_index=True, width="stretch", height=260,
                 column_config={c: st.column_config.NumberColumn(format="$%,.0f")
                                for c in ("costo_actual", "costo_propuesto", "ahorro")})

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
                         s.end.strftime("%H:%M"), s.jornada_code])
        return pd.DataFrame(rows, columns=SCHEDULE_COLS + ["jornada"])

    d1, d2 = st.columns(2)
    d1.download_button(f"Descargar nueva programación — {choice.lower()} (CSV)",
                       pd.concat([proposed_flat(k, x) for k, x in results.items()]).to_csv(index=False).encode(),
                       f"nueva_programacion_{pol}_dias.csv", type="primary", width="stretch")
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
    with st.expander("¿Cómo se genera la programación? (CP-SAT)"):
        st.markdown((ROOT / "docs" / "app_method.md").read_text(encoding="utf-8"))


# ================================================================ navigation
P_HOME = st.Page(page_home, title="Inicio", icon=":material/home:", default=True)
P_DATA = st.Page(page_data, title="Datos", icon=":material/upload_file:", url_path="datos")
P_DIAG = st.Page(page_diag, title="Diagnóstico", icon=":material/monitoring:", url_path="diagnostico")
P_NEW = st.Page(page_new, title="Nueva programación", icon=":material/event_available:", url_path="nueva-programacion")
nav = st.navigation([P_HOME, P_DATA, P_DIAG, P_NEW], position="top")
sidebar()
nav.run()
