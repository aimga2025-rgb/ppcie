# Data files (private)

This project expects some Excel/CSV inputs under `data/`, but **do not commit real production files** to a public repository.

Recommended safe workflow:

- Keep the repository public for code only.
- Load sensitive Excel files at runtime (e.g., via Streamlit upload or from private storage).
- Commit only:
  - schemas/templates with no sensitive rows, and/or
  - synthetic/anonymized sample data.

Ignored by default (see `.gitignore`):

- `*.xlsx` / `*.xlsm`
- `data/models/` (trained artifacts, encoders)
- `data/saved_plan_history.csv`, `data/live_planner_cache.json`
- `data/skill_matrix_normalized_cache*.{csv,json}`

If a sensitive file was ever committed, remove it from git history (e.g., using `git filter-repo`) before pushing publicly.
