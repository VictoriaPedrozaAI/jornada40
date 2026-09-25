# Deploy to Hugging Face Spaces (free CPU)

The repo is already a Space: `README.md` starts with the Space config (`sdk: docker`, `app_port: 8501`) and the `Dockerfile` runs Streamlit on 8501 as user 1000. The Streamlit SDK option in Spaces is deprecated; Docker + Streamlit is the supported path.

## Option A — CLI upload (simplest, handles binary files)

Verified with `huggingface_hub` 2.0 (`hf` CLI):

```bash
pip install -U huggingface_hub
hf auth login                                         # paste a token with WRITE access
hf repos create <user>/jornada40 --type space --sdk docker          # add --private for client data
cd jornada40                                          # the unzipped project folder (contains Dockerfile)
hf upload <user>/jornada40 . . --type space --exclude "tests/*" --exclude "__pycache__/*"
```

Alternative without CLI for the create step: huggingface.co → New → Space → SDK **Docker** → template **Blank** → hardware **CPU basic (free)**.

## Option B — git

Spaces reject plain-git binary files (`.png`, `.xlsx`), so track them with LFS first:

```bash
git lfs install
git lfs track "*.png" "*.xlsx"
git remote add space https://huggingface.co/spaces/<user>/jornada40
git add .gitattributes && git add . && git commit -m "Jornada40 MVP"
git push space main
```

## After pushing
- Build log: Space page → *Logs*. First build ≈ 3–5 min (OR-Tools wheel).
- App URL: `https://<user>-jornada40.hf.space`.
- Free CPU Spaces sleep after inactivity; the first visit wakes it (≈ 30 s). Open it before the demo call.
- File uploads work because the container starts Streamlit with XSRF/CORS disabled (required inside the Spaces iframe).

## Local check before pushing

```bash
pip install -r requirements-dev.txt && python -m pytest -q
docker build -t jornada40 . && docker run -p 8501:8501 jornada40
```

## Does it fit the free tier (CPU Basic: 2 vCPU, 16 GB)?
Yes. Measured on 1 vCPU (worse than the free tier): load demo 0.6 s, diagnosis of 50 stores 0.9 s, optimization of 50 stores × 2 scenarios ≈ 10 s, parsing an uploaded chain of 24 stores / 11.5k shifts 0.6 s; peak memory ≈ 200 MB for the pipeline (plus ~150 MB Streamlit). CP-SAT uses as many workers as there are CPUs (2 on the free tier).

Caveats: the Space sleeps after inactivity (open it before a demo); simultaneous "Generar" clicks from several users share the 2 vCPU and run slower; disk is ephemeral (nothing is stored between sessions — uploads live only in the session's memory). For real client payroll data, make the Space **private** or move to a paid/self-hosted deployment.
