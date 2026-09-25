---
title: Jornada40
emoji: 📅
colorFrom: green
colorTo: gray
sdk: docker
app_port: 8501
pinned: false
short_description: Retail roster under Mexico's 40-h week, savings in MXN
---

# Jornada40

Weekly roster proposal for a Mexican retailer under the 40 h/week reform, with the avoided labor cost in MXN versus the current roster.

**Run locally**

```bash
pip install -r requirements-dev.txt
python -m pytest -q                       # 63 tests
streamlit run app.py                      # http://localhost:8501
```

**Regenerate demo data / results**

```bash
python -m jornada40.synth.build_dataset   # traffic, requirement (50 stores)
python -m jornada40.synth.baseline_roster # bad-planning baseline, store 20
python -m jornada40.pipeline              # optimize all 50 stores -> data/synthetic/results/
```

**Test company for the user journey:** `data/test_company/` (`python scripts/make_test_company.py`).

**Deploy to Hugging Face Spaces** — see `docs/deploy_hf_spaces.md`.

## Map

- `app.py` — Streamlit UI (Spanish), 4-page menu: Inicio · Datos · Diagnóstico · Nueva programación
- `jornada40/checks.py` — pre-solve capacity checks
- `jornada40/optimizer.py` — CP-SAT optimizer (two-stage)
- `jornada40/pipeline.py` — current vs proposed, savings; chain run
- `jornada40/ingest/flat.py` — app CSV templates and loader (`data/templates_app/`)
- `HANDOVER.md` — state, decisions, open questions (start here)
- `docs/input_formats.md` — what the client uploads (CSV templates in `data/templates/`)
- `docs/traffic_data_assessment.md` — visit data assessment, peak hours, synthetic assumptions
- `jornada40/demand.py` — forecast, staffing requirement, peak detection
- `jornada40/synth/` — traffic profile + generator (`python -m jornada40.synth.build_dataset`)
- `docs/baseline_roster_review.md` — client roster review + baseline "before" (`python -m jornada40.synth.baseline_roster`)
- `jornada40/cost.py` — cost engine v0 (MXN)
- `docs/LFT_rules.md` — legal rules and parameters
- `docs/employee_csv_schema.md` — roster input format
- `jornada40/ingest/employees.py` — roster loader and validation
- `docs/current_schedule_input.md` — current-schedule import + compliance rules
- `jornada40/ingest/shift_grid.py` — Excel shift-grid importer
- `jornada40/shifts.py` — shift model, diurna/mixta/nocturna classification
- `jornada40/compliance.py` — LFT checks, overtime bands, hourly coverage gaps/overstaffing

