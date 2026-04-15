# Deploy the *same* dashboard as `ppc.py` (Dash)

If you want the dashboard to look/behave exactly like running `ppc.py`, you must deploy the Dash app (not Streamlit).

This repo includes a deployment entrypoint:
- `wsgi.py` exposes `server = app.server` from `ppc.py`.

## Option A — Render (recommended)
1. Create a new **Web Service** from this GitHub repo.
2. **Build Command**:
   - `pip install -r requirements_dash.txt`
3. **Start Command**:
   - `gunicorn wsgi:server --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
4. Add environment variables if needed:
   - `PPC_HOST=0.0.0.0` (some platforms ignore this because gunicorn controls bind)
   - `PPC_LIVE_ENDPOINT=...` (if you use the live API)

## Option B — Railway / Fly / Heroku-style
- `Procfile` is included:
  - `web: gunicorn wsgi:server --bind 0.0.0.0:$PORT --workers 2 --timeout 120`

## Important: private Excel data
- Do **not** commit sensitive Excel files to a public repo.
- Your Dash app currently expects local paths like `data/Sewing loading Plan..xlsx`.
  On a server you must provide that file securely (private disk / private storage / upload flow).

If you tell me which hosting you want (Render / Railway / Fly / something else), I can add the exact config files for that host without touching your `ppc.py` logic.
