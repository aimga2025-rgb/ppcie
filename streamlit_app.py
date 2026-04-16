import hashlib
import io
import json
import secrets
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


st.set_page_config(page_title="MG PPC Dashboard", layout="wide")


def _ensure_query_sid() -> str:
    """Ensure the URL contains a per-user SID so stored uploads don't leak across users."""
    sid = st.query_params.get("sid")
    if isinstance(sid, list):
        sid = sid[0] if sid else ""
    sid = str(sid or "").strip()
    if not sid:
        sid = secrets.token_urlsafe(12)
        st.query_params["sid"] = sid
        st.stop()
    return sid


SID = _ensure_query_sid()
BASE_UPLOAD_DIR = Path(tempfile.gettempdir()) / "ppc_private_uploads"


def _upload_dir() -> Path:
    return BASE_UPLOAD_DIR / SID


def _upload_state_path() -> Path:
    return _upload_dir() / "upload_state.json"


def _inject_theme_css() -> None:
    # Reuse the look-and-feel from ppc.py (dark background, accent colors).
    st.markdown(
        """
<style>
  .stApp { background: #0a0e1a; color: #e2e8f0; }
  section[data-testid="stSidebar"] { background: #0d1224; }
  h1, h2, h3, h4 { font-family: Rajdhani, system-ui, sans-serif; }
  .brand { font-size: 26px; font-weight: 700; background: linear-gradient(90deg, #00c6ff, #0072ff);
           -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .muted { color: #64748b; font-size: 12px; }
  div[data-testid="stMetric"] { background: #111827; border: 1px solid #1e2d4a; border-radius: 14px; padding: 12px; }
</style>
""",
        unsafe_allow_html=True,
    )


def _canon(text: str) -> str:
    return "".join(ch.lower() for ch in str(text or "") if ch.isalnum())


@st.cache_data(show_spinner=False)
def _excel_sheet_names(file_bytes: bytes) -> list[str]:
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    return list(xl.sheet_names)


@st.cache_data(show_spinner=False)
def _load_excel_sheet(file_bytes: bytes, sheet_name: str, **kwargs: Any) -> pd.DataFrame:
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    return pd.read_excel(xl, sheet_name=sheet_name, **kwargs)


@st.cache_data(show_spinner=False)
def _load_csv(file_bytes: bytes, **kwargs: Any) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(file_bytes), **kwargs)


REQUIRED_SEWING_SHEET = "Sewing Loading Plan"
REQUIRED_SEWING_COLS = ["Cstmr", "Style", "SAM", "Plan Qty", "Line #", "Strt Sw Out Dt", "End Sew Date"]

# Per-user storage (keyed by SID in the URL) to survive browser refresh.
# Note: Streamlit Cloud may wipe /tmp on restart/redeploy.


def _detect_inputs(files) -> dict[str, Any]:
    sewing_plan = None
    skill_matrix = None
    plan_history = None
    holidays = None
    others = []

    for f in files or []:
        name = getattr(f, "name", "") or ""
        norm = _canon(name)
        suffix = name.lower().split(".")[-1] if "." in name else ""
        file_bytes = f.getvalue()

        if suffix == "xlsx":
            try:
                sheets = _excel_sheet_names(file_bytes)
            except Exception:
                sheets = []

            if sewing_plan is None and REQUIRED_SEWING_SHEET in sheets:
                sewing_plan = f
                continue

            if skill_matrix is None and ("skill" in norm and "matrix" in norm):
                skill_matrix = f
                continue

            others.append(f)
            continue

        if suffix == "csv":
            if plan_history is None and ("saved" in norm and "plan" in norm and "history" in norm):
                plan_history = f
                continue

            if holidays is None and ("holiday" in norm or "publicholiday" in norm):
                holidays = f
                continue

            others.append(f)
            continue

        others.append(f)

    return {
        "sewing_plan": sewing_plan,
        "skill_matrix": skill_matrix,
        "plan_history": plan_history,
        "holidays": holidays,
        "others": others,
    }


def _validate_sewing_plan(xlsx_file) -> tuple[bool, str, pd.DataFrame | None]:
    if xlsx_file is None:
        return False, "Missing: Sewing Loading Plan workbook (.xlsx)", None

    try:
        if isinstance(xlsx_file, Path):
            file_bytes = xlsx_file.read_bytes()
        else:
            file_bytes = xlsx_file.getvalue()
        df = _load_excel_sheet(file_bytes, REQUIRED_SEWING_SHEET, skiprows=2)
    except Exception as exc:
        return False, f"Could not read sheet '{REQUIRED_SEWING_SHEET}': {type(exc).__name__}: {exc}", None

    missing = [c for c in REQUIRED_SEWING_COLS if c not in df.columns]
    if missing:
        return False, f"Missing required columns: {', '.join(missing)}", df
    return True, "OK", df


def _write_private_upload_to_temp(uploaded_file, suffix: str) -> Path:
    file_bytes = uploaded_file.getvalue()
    digest = hashlib.sha1(file_bytes).hexdigest()[:12]
    out_dir = _upload_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"upload_{digest}{suffix}"
    out_path.write_bytes(file_bytes)
    return out_path


def _save_upload_state(state: dict[str, Any]) -> None:
    out_dir = _upload_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = _upload_state_path()
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(state_path)


def _load_upload_state() -> dict[str, Any] | None:
    """Load persisted state.

    Supports both formats:
    - legacy: {"sewing_plan": "/tmp/...", ...}
    - current: {"files": {...}, "supabase": {...}}
    """
    try:
        state_path = _upload_state_path()
        if not state_path.exists():
            return None
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None

        files_payload = payload.get("files")
        supabase_payload = payload.get("supabase")

        if files_payload is None and all(isinstance(v, str) for v in payload.values()):
            # Back-compat legacy format.
            files_payload = payload
            supabase_payload = None

        files_out: dict[str, Path] = {}
        if isinstance(files_payload, dict):
            for key, value in files_payload.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    continue
                path = Path(value)
                if path.exists():
                    files_out[key] = path

        supabase_out: dict[str, str] = {}
        if isinstance(supabase_payload, dict):
            for key, value in supabase_payload.items():
                if isinstance(key, str) and isinstance(value, str) and value.strip():
                    supabase_out[key] = value.strip()

        if not files_out and not supabase_out:
            return None

        return {"files": files_out, "supabase": supabase_out or None}
    except Exception:
        return None


def _clear_upload_state() -> None:
    try:
        out_dir = _upload_dir()
        state_path = _upload_state_path()
        if state_path.exists():
            state_path.unlink()
        # Remove uploaded payload files for this SID.
        if out_dir.exists():
            for p in out_dir.glob("upload_*"):
                try:
                    p.unlink()
                except Exception:
                    pass
    except Exception:
        pass


def _as_path(file_or_path, suffix: str) -> Path | None:
    if file_or_path is None:
        return None
    if isinstance(file_or_path, Path):
        return file_or_path
    return _write_private_upload_to_temp(file_or_path, suffix)


@st.cache_data(show_spinner=False)
def _read_saved_plans_csv(path_str: str) -> pd.DataFrame:
    path = Path(path_str)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _kpis_from_df(df: pd.DataFrame) -> tuple[str, str, str, str]:
    if df is None or df.empty:
        return "0", "0", "0%", "0"

    bpo_series = df["BPO Number"] if "BPO Number" in df.columns else df.get("PO#", pd.Series([""] * len(df), index=df.index))
    df = df.assign(
        **{
            "Line #": df.get("Line #", "").astype(str).str.strip(),
            "BPO Number": bpo_series,
            "Pln Eff %": df.get("Pln Eff %", ""),
            "Plan Qty": pd.to_numeric(df.get("Plan Qty", 0), errors="coerce").fillna(0),
        }
    )

    active_lines = int(df["Line #"][df["Line #"] != ""].nunique())
    active_orders = int((df["BPO Number"].astype(str).str.strip() != "").sum())

    eff_series = df["Pln Eff %"].astype(str).str.replace("%", "", regex=False).str.strip()
    eff_numeric = pd.to_numeric(eff_series, errors="coerce").dropna()
    if eff_numeric.empty:
        avg_eff = "0%"
    else:
        mean_eff = float(eff_numeric.mean())
        avg_eff = f"{(mean_eff * 100.0 if mean_eff <= 1.5 else mean_eff):.0f}%"

    total_plan_qty = float(df["Plan Qty"].sum() or 0)
    total_plan_qty_str = f"{total_plan_qty:,.0f}"
    return str(active_lines), str(active_orders), avg_eff, total_plan_qty_str


def _pick_month_options(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty or "Ex-mill Mnth" not in df.columns:
        return []
    month_values = [str(v).strip() for v in df["Ex-mill Mnth"].dropna().tolist() if str(v).strip()]
    seen = set()
    out: list[str] = []
    for m in month_values:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _ensure_state() -> None:
    st.session_state.setdefault("live_rows", [])
    st.session_state.setdefault("live_last_fetch", None)
    st.session_state.setdefault("prediction_queue", [])
    st.session_state.setdefault("pending_prediction", None)
    st.session_state.setdefault("last_training", None)


_inject_theme_css()
_ensure_state()

st.markdown('<div class="brand">MG PPC</div>', unsafe_allow_html=True)
st.markdown('<div class="muted">Production Control</div>', unsafe_allow_html=True)

def _download_supabase_object_to_path(bucket: str, object_path: str) -> Path:
    """Download a Supabase Storage object into the per-user upload dir and return the local Path."""
    url = str(st.secrets.get("SUPABASE_URL", "") or "").strip()
    key = str(
        st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")
        or st.secrets.get("SUPABASE_ANON_KEY", "")
        or ""
    ).strip()

    if not url or not key:
        raise RuntimeError(
            "Missing Supabase secrets. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (recommended) in Streamlit secrets."
        )

    try:
        from supabase import create_client  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Supabase client not installed: {exc}")

    client = create_client(url, key)
    bucket = str(bucket or "").strip()
    object_path = str(object_path or "").strip().lstrip("/")
    if not bucket or not object_path:
        raise ValueError("Bucket and object path are required")

    data = client.storage.from_(bucket).download(object_path)
    if not isinstance(data, (bytes, bytearray)):
        # Some versions may return a Response-like object.
        try:
            data = bytes(data)  # type: ignore
        except Exception:
            raise RuntimeError("Unexpected Supabase download response")

    suffix = ("." + object_path.split(".")[-1].lower()) if "." in object_path else ""
    digest = hashlib.sha1(bytes(data)).hexdigest()[:12]
    out_dir = _upload_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"supabase_{digest}{suffix}"
    out_path.write_bytes(bytes(data))
    return out_path


with st.sidebar:
    st.header("Inputs")
    page = st.radio("Navigation", ["Dashboard", "PPC Planner", "Order Tracker"], index=0)

    if st.button("Clear stored uploads", use_container_width=True):
        _clear_upload_state()
        st.session_state.pop("live_rows", None)
        st.session_state.pop("live_last_fetch", None)
        st.session_state.pop("prediction_queue", None)
        st.session_state.pop("pending_prediction", None)
        st.session_state.pop("last_training", None)
        st.rerun()

    data_source = st.radio("Data source", ["Upload", "Supabase"], index=0, horizontal=True)

    uploaded_files = None
    if data_source == "Upload":
        uploaded_files = st.file_uploader(
            "Upload files (Excel/CSV)",
            type=["xlsx", "csv"],
            accept_multiple_files=True,
            help="Upload your private Excel at runtime (do not commit to Git).",
        )
    else:
        st.caption("Load private files from Supabase Storage (persistent across refresh/restarts).")
        bucket = st.text_input("Supabase bucket", value=str(st.session_state.get("sb_bucket", "")))
        sewing_obj = st.text_input("Sewing plan object path (.xlsx)", value=str(st.session_state.get("sb_sewing", "")))
        history_obj = st.text_input("Plan history object path (.csv)", value=str(st.session_state.get("sb_history", "")))
        skill_obj = st.text_input("Skill matrix object path (.xlsx) (optional)", value=str(st.session_state.get("sb_skill", "")))

        if st.button("Load from Supabase", use_container_width=True, type="primary"):
            st.session_state["sb_bucket"] = bucket
            st.session_state["sb_sewing"] = sewing_obj
            st.session_state["sb_history"] = history_obj
            st.session_state["sb_skill"] = skill_obj

            try:
                files_state: dict[str, str] = {}
                supa_state: dict[str, str] = {
                    "bucket": str(bucket or "").strip(),
                    "sewing_plan": str(sewing_obj or "").strip(),
                    "plan_history": str(history_obj or "").strip(),
                    "skill_matrix": str(skill_obj or "").strip(),
                }

                if sewing_obj:
                    local = _download_supabase_object_to_path(bucket, sewing_obj)
                    files_state["sewing_plan"] = str(local)
                if history_obj:
                    local = _download_supabase_object_to_path(bucket, history_obj)
                    files_state["plan_history"] = str(local)
                if skill_obj:
                    local = _download_supabase_object_to_path(bucket, skill_obj)
                    files_state["skill_matrix"] = str(local)

                _save_upload_state({"files": files_state, "supabase": supa_state})
                st.success("Loaded from Supabase.")
                st.rerun()
            except Exception as exc:
                st.error(f"Supabase load failed: {exc}")

inputs: dict[str, Any]
if uploaded_files:
    inputs = _detect_inputs(uploaded_files)
    # Persist last-known good file paths for refresh reuse.
    files_state: dict[str, str] = {}
    sewing_path = _as_path(inputs.get("sewing_plan"), ".xlsx")
    if sewing_path:
        files_state["sewing_plan"] = str(sewing_path)
    skill_path = _as_path(inputs.get("skill_matrix"), ".xlsx")
    if skill_path:
        files_state["skill_matrix"] = str(skill_path)
    history_path = _as_path(inputs.get("plan_history"), ".csv")
    if history_path:
        files_state["plan_history"] = str(history_path)
    holidays_path = _as_path(inputs.get("holidays"), ".csv")
    if holidays_path:
        files_state["holidays"] = str(holidays_path)
    if files_state:
        _save_upload_state({"files": files_state, "supabase": None})
else:
    restored = _load_upload_state()
    if restored:
        restored_files: dict[str, Path] = restored.get("files") or {}
        supa: dict[str, str] | None = restored.get("supabase")

        # If local files were wiped (e.g., container restart) but Supabase config exists, re-download.
        if supa and isinstance(supa, dict):
            bucket = supa.get("bucket", "")
            if "sewing_plan" not in restored_files and supa.get("sewing_plan"):
                try:
                    p = _download_supabase_object_to_path(bucket, supa["sewing_plan"])
                    restored_files["sewing_plan"] = p
                except Exception:
                    pass
            if "plan_history" not in restored_files and supa.get("plan_history"):
                try:
                    p = _download_supabase_object_to_path(bucket, supa["plan_history"])
                    restored_files["plan_history"] = p
                except Exception:
                    pass
            if "skill_matrix" not in restored_files and supa.get("skill_matrix"):
                try:
                    p = _download_supabase_object_to_path(bucket, supa["skill_matrix"])
                    restored_files["skill_matrix"] = p
                except Exception:
                    pass

        inputs = {
            "sewing_plan": restored_files.get("sewing_plan"),
            "skill_matrix": restored_files.get("skill_matrix"),
            "plan_history": restored_files.get("plan_history"),
            "holidays": restored_files.get("holidays"),
            "others": [],
        }
        st.sidebar.info("Using your last files after refresh.")
        st.sidebar.caption(
            "Note: Streamlit clears the upload widget on refresh; the app can still reuse stored files."
        )
        st.sidebar.write(
            {
                "sewing_plan": str(inputs["sewing_plan"]) if inputs["sewing_plan"] else None,
                "skill_matrix": str(inputs["skill_matrix"]) if inputs["skill_matrix"] else None,
                "plan_history": str(inputs["plan_history"]) if inputs["plan_history"] else None,
                "holidays": str(inputs["holidays"]) if inputs["holidays"] else None,
            }
        )
    else:
        inputs = {"sewing_plan": None, "skill_matrix": None, "plan_history": None, "holidays": None, "others": []}

sewing_ok, sewing_msg, sewing_df_preview = _validate_sewing_plan(inputs["sewing_plan"])

if page != "Order Tracker":
    st.caption("Streamlit version of the PPC dashboard. Keep your Excel private.")

try:
    import ppc as ppc_dash
except Exception as exc:
    st.error(f"Could not import ppc.py. Missing dependency? {type(exc).__name__}: {exc}")
    st.stop()


def _sync_private_inputs_into_ppc() -> None:
    # Wire uploaded files into ppc.py without modifying ppc.py itself.
    sewing_obj = inputs.get("sewing_plan")
    if sewing_ok and sewing_obj is not None:
        plan_path = _as_path(sewing_obj, ".xlsx")
        if plan_path is not None:
            ppc_dash.EXCEL_PATH = Path(plan_path)
        try:
            ppc_dash._load_sewing_plan_df.cache_clear()
        except Exception:
            pass
        try:
            ppc_dash._lookup_inputs_by_po.cache_clear()
        except Exception:
            pass

    skill_obj = inputs.get("skill_matrix")
    if skill_obj is not None:
        skill_path = _as_path(skill_obj, ".xlsx")
        if skill_path is not None:
            ppc_dash.SKILL_MATRIX_FILE_HINT = str(skill_path)
        # Clear cached skill matrix loads if present.
        for name in ("_load_skill_matrix_normalized", "_skill_matrix_resources_for_line"):
            fn = getattr(ppc_dash, name, None)
            if fn is not None and hasattr(fn, "cache_clear"):
                try:
                    fn.cache_clear()
                except Exception:
                    pass

    history_obj = inputs.get("plan_history")
    if history_obj is not None:
        # Prefer using the downloaded/uploaded file path directly.
        # On Streamlit Cloud, writing into the repo folder can be unreliable.
        try:
            if isinstance(history_obj, Path):
                ppc_dash.PLAN_HISTORY_PATH = Path(history_obj)
            else:
                # If we got an UploadedFile-like object, persist it and point PPC to it.
                tmp_path = _as_path(history_obj, ".csv")
                if tmp_path is not None:
                    ppc_dash.PLAN_HISTORY_PATH = Path(tmp_path)
        except Exception:
            pass

        # Best-effort: also copy into the default location (ignored if not writable).
        try:
            ppc_dash.PLAN_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


_sync_private_inputs_into_ppc()


if page == "Dashboard":
    st.subheader("📊 Production Dashboard")

    plan_history_path = inputs.get("plan_history") or ppc_dash.PLAN_HISTORY_PATH
    plan_df = _read_saved_plans_csv(str(plan_history_path))
    st.caption(f"Saved plan history rows: {len(plan_df)}")
    month_options = _pick_month_options(plan_df)

    col1, col2, col3 = st.columns(3)
    with col1:
        month_value = st.selectbox("Filter by Ex-mill month", [""] + month_options, index=0)
        month_value = month_value or None
    with col2:
        search_bpo = st.text_input("Search by BPO Number")
    with col3:
        st.write("")
        st.write("")
        st.download_button(
            "Export CSV",
            data=plan_df.to_csv(index=False).encode("utf-8"),
            file_name="saved_plan_history_export.csv",
            mime="text/csv",
            disabled=plan_df.empty,
        )

    # KPI logic mirrors ppc.py: KPIs come from saved plan history (not from the Sewing Plan upload).
    df_for_kpi = plan_df
    if month_value and "Ex-mill Mnth" in plan_df.columns:
        df_for_kpi = plan_df[plan_df["Ex-mill Mnth"].astype(str).str.strip() == str(month_value).strip()]
        if df_for_kpi.empty:
            df_for_kpi = plan_df

    k1, k2, k3, _k4_plain = _kpis_from_df(df_for_kpi)
    try:
        total_plan_qty_num = float(pd.to_numeric(df_for_kpi.get("Plan Qty", 0), errors="coerce").fillna(0).sum() or 0)
        k4 = ppc_dash._format_plan_qty(total_plan_qty_num)
    except Exception:
        k4 = _k4_plain

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active Lines", k1)
    m2.metric("Active Orders", k2)
    m3.metric("Avg Efficiency", k3)
    m4.metric("Total Plan Qty", k4)

    st.markdown("#### All Month Plans")

    if plan_df.empty:
        st.info(
            "No saved plans found yet. To populate this dashboard like your local Dash app, either:\n"
            "• Upload `saved_plan_history.csv` from your PC, OR\n"
            "• Go to 'PPC Planner' → Refresh live feed → Generate predictions → OK (Save)."
        )
    else:
        df = df_for_kpi.copy()

        bpo_query_text = str(search_bpo or "").strip().upper()
        if bpo_query_text:
            if "BPO Number" not in df.columns and "PO#" in df.columns:
                df["BPO Number"] = df["PO#"]
            if "BPO Number" not in df.columns:
                df["BPO Number"] = ""
            bpo_series = df["BPO Number"].astype(str).str.upper()
            df = df[bpo_series.str.contains(bpo_query_text, na=False)]

        if df.empty:
            label = "All months" if not month_value else f"Month: {month_value}"
            if bpo_query_text:
                label = f"{label} | BPO Number: {bpo_query_text}"
            st.warning(f"No saved plans available for selected filter. ({label})")
        else:
            for required in [
                "Line #",
                "BPO Number",
                "PO#",
                "Cstmr",
                "Style",
                "SAM",
                "Plan Qty",
                "Pln Eff %",
                "P.Dy Cpcty",
                "Com Dys Wk",
                "EX-MILL",
                "Created At",
            ]:
                if required not in df.columns:
                    df[required] = ""

            # Mirror Dash grouping logic to match the local dashboard table.
            line_numbers = df["Line #"].astype(str).str.extract(r"(\d+)", expand=False)
            df["_line_sort"] = pd.to_numeric(line_numbers, errors="coerce").fillna(10**6)
            if "Created At" in df.columns:
                df = df.sort_values(by=["_line_sort", "Line #", "Created At"], ascending=[True, True, False])
            else:
                df = df.sort_values(by=["_line_sort", "Line #"], ascending=[True, True])

            month_stats = ppc_dash._month_workday_stats(month_value)
            line_machines = 58
            working_mins_per_day = 480
            available_sam = month_stats["work_days"] * line_machines * working_mins_per_day

            grouped_rows: list[dict[str, Any]] = []
            for line_value, group in df.groupby(df["Line #"].astype(str), sort=False):
                planned_qty = float(pd.to_numeric(group["Plan Qty"], errors="coerce").fillna(0).sum())
                avg_sam = float(pd.to_numeric(group["SAM"], errors="coerce").dropna().mean() or 0.0)

                eff_raw = group["Pln Eff %"].astype(str).str.replace("%", "", regex=False).str.strip()
                eff_numeric = pd.to_numeric(eff_raw, errors="coerce").dropna()
                if not eff_numeric.empty:
                    avg_eff = float(eff_numeric.mean())
                    planned_eff_pct = avg_eff * 100.0 if avg_eff <= 1.5 else avg_eff
                else:
                    planned_eff_pct = 75.0
                planned_eff_pct = max(75.0, float(planned_eff_pct))

                produced_sam = planned_qty * avg_sam
                work_days = int(month_stats["work_days"])
                per_day_cap = (planned_qty / work_days) if work_days > 0 else 0.0

                grouped_rows.append(
                    {
                        "SR#": None,
                        "Line": str(line_value),
                        "Planned Quantity": int(round(planned_qty)),
                        "Average SAM": round(avg_sam, 1),
                        "Planned Efficiency": f"{planned_eff_pct:.0f}%",
                        "Per day Capacity": int(round(per_day_cap)),
                        "Work Days": int(month_stats["work_days"]),
                        "Sundays": int(month_stats["sundays"]),
                        "Holiday": int(month_stats["holiday"]),
                        "Month Days": int(month_stats["month_days"]),
                        "Available SAM": int(available_sam),
                        "Produced SAM": int(round(produced_sam)),
                    }
                )

            table_df = pd.DataFrame(grouped_rows)
            if not table_df.empty:
                table_df["SR#"] = range(1, len(table_df) + 1)

            label = "All months" if not month_value else f"Month: {month_value}"
            if bpo_query_text:
                label = f"{label} | BPO Number: {bpo_query_text}"
            st.caption(f"{label} | {len(table_df)} line(s)")
            st.dataframe(table_df, use_container_width=True, height=520)


elif page == "PPC Planner":
    st.subheader("📋 PPC Planner")
    st.markdown("#### Live BPO Number Planner")

    if not sewing_ok:
        st.warning(f"Sewing plan required for AI prediction: {sewing_msg}")
    else:
        st.success("Sewing plan detected and loaded for AI inputs.")

    top_left, top_right = st.columns([3, 1])
    with top_left:
        last_fetch = st.session_state.get("live_last_fetch")
        if last_fetch:
            st.caption(f"Last live fetch: {last_fetch}")
        else:
            st.caption("Last live fetch: not yet")
    with top_right:
        force = st.button("Refresh live feed", use_container_width=True)

    if force:
        try:
            st.session_state.live_rows = ppc_dash._fetch_live_planner_records(force_refresh=True)
            st.session_state.live_last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as exc:
            st.error(f"Live fetch failed: {type(exc).__name__}: {exc}")

    live_rows = st.session_state.get("live_rows") or []
    if not isinstance(live_rows, list):
        live_rows = []

    if not live_rows:
        st.info("No current-date live rows loaded yet. Click 'Refresh live feed'.")
    else:
        live_df = pd.DataFrame(live_rows)
        st.dataframe(live_df, use_container_width=True, height=360)

    st.divider()

    st.markdown("#### AI Models")
    train_col1, train_col2 = st.columns([1, 3])
    with train_col1:
        do_train = st.button("Train AI Models", use_container_width=True, disabled=not sewing_ok)
    with train_col2:
        last_train = st.session_state.get("last_training")
        if last_train:
            st.success(last_train)
        else:
            st.info("Model not trained in this Streamlit session.")

    if do_train:
        try:
            stats = ppc_dash.train_ai_models(ppc_dash.EXCEL_PATH)
            ppc_dash._load_encoder_cache()
            msg = (
                f"Training complete: {stats['rows']} rows, {stats['classes']} line classes, "
                f"line acc={stats['line_train_acc']:.2%}, days MAE={stats['days_train_mae']:.2f}."
            )
            st.session_state.last_training = msg
            st.success(msg)
        except Exception as exc:
            st.error(f"Training failed: {exc}")

    st.divider()
    st.markdown("#### Predicted Plan Results")


    def _build_prediction_queue(live_rows_payload: list[dict]) -> list[dict]:
        saved_po_keys = {
            ppc_dash._normalize_po(ppc_dash._get_plan_number(plan))
            for plan in ppc_dash.SAVED_PLANS
            if isinstance(plan, dict)
        }

        candidate_rows: list[dict] = []
        for row in live_rows_payload:
            po_try = ppc_dash._normalize_po(ppc_dash._get_plan_number(row))
            if po_try and po_try not in saved_po_keys:
                candidate_rows.append(row)

        model_line, model_days, encoders, meta = ppc_dash._load_artifacts()
        defaults = meta.get("defaults", {}) if isinstance(meta, dict) else {}

        prediction_queue: list[dict] = []
        for candidate in candidate_rows:
            po_number = ppc_dash._get_plan_number(candidate)
            sheet_inputs = ppc_dash._lookup_inputs_by_po(po_number)
            live_inputs = candidate
            sale_order_creation_date = ppc_dash._get_live_sale_order_creation_date(live_inputs)

            customer = live_inputs.get("customer") or sheet_inputs.get("customer")
            style = live_inputs.get("style") or sheet_inputs.get("style")
            product = live_inputs.get("product") or sheet_inputs.get("product") or "New"
            sam = live_inputs.get("sam") if live_inputs.get("sam") is not None else sheet_inputs.get("sam")
            plan_qty = live_inputs.get("plan_qty") if live_inputs.get("plan_qty") is not None else sheet_inputs.get("plan_qty")

            if not customer or not style or not product or sam is None or plan_qty is None:
                continue
            if float(sam) <= 0 or float(plan_qty) <= 0:
                continue

            po_inputs = live_inputs or sheet_inputs
            fabric = po_inputs.get("fabric") or defaults.get("Fabric") or "UNKNOWN"
            wash_type = po_inputs.get("wash_type") or defaults.get("wash Type") or "Unknown"
            color = po_inputs.get("color") or defaults.get("Color") or "UNKNOWN"

            pln_eff_num = po_inputs.get("pln_eff_num")
            if pln_eff_num is None:
                pln_eff_num = defaults.get("Pln Eff Num", 0.75)

            bal_sew = po_inputs.get("bal_sew")
            if bal_sew is None:
                bal_sew = float(plan_qty)

            row = {
                "Cstmr": ppc_dash._encode_value(encoders["Cstmr"], customer, "customer", defaults.get("Cstmr")),
                "Style": ppc_dash._encode_value(encoders["Style"], style, "style", defaults.get("Style")),
                "Product": ppc_dash._encode_value(encoders["Product"], product, "product", defaults.get("Product")),
                "Fabric": ppc_dash._encode_value(encoders["Fabric"], fabric, "fabric", defaults.get("Fabric")),
                "wash Type": ppc_dash._encode_value(encoders["wash Type"], wash_type, "wash type", defaults.get("wash Type")),
                "Color": ppc_dash._encode_value(encoders["Color"], color, "color", defaults.get("Color")),
                "SAM": float(sam),
                "Plan Qty": float(plan_qty),
                "Pln Eff Num": float(pln_eff_num),
                "Bal Sew": float(bal_sew),
            }

            X_pred = pd.DataFrame([row], columns=ppc_dash.FEATURES)
            line_encoded = int(model_line.predict(X_pred)[0])
            pred_line = encoders["Line #"].inverse_transform([line_encoded])[0]
            pred_days = max(1, int(round(float(model_days.predict(X_pred)[0]))))

            top_line_recos = []
            try:
                proba = model_line.predict_proba(X_pred)[0]
                class_codes = list(model_line.classes_)
                ranked_idx = sorted(range(len(proba)), key=lambda i: float(proba[i]), reverse=True)[:3]
                for rank, idx in enumerate(ranked_idx, start=1):
                    code = int(class_codes[idx])
                    line_name = encoders["Line #"].inverse_transform([code])[0]
                    top_line_recos.append({"rank": rank, "line": str(line_name), "score": float(proba[idx])})
            except Exception:
                top_line_recos = [{"rank": 1, "line": str(pred_line), "score": 1.0}]

            pred_row = ppc_dash._build_prediction_row(
                po_number=po_number,
                customer=customer,
                style=style,
                product=product,
                sam=float(sam),
                plan_qty=float(plan_qty),
                pred_line=pred_line,
                pred_days=pred_days,
                expected_shipment_date_raw=po_inputs.get("expected_shipment_date") or po_inputs.get("EX-MILL") or po_inputs.get("exMill"),
                sale_order_creation_date_raw=sale_order_creation_date,
            )

            prediction_queue.append(
                {
                    "po_number": po_number,
                    "pred_row": pred_row,
                    "top_line_recos": top_line_recos,
                    "pred_days": pred_days,
                    "pred_line": str(pred_line),
                }
            )

        return prediction_queue


    gen_col1, gen_col2 = st.columns([1, 3])
    with gen_col1:
        gen = st.button("Generate predictions", use_container_width=True, disabled=not (sewing_ok and live_rows))
    with gen_col2:
        st.caption("This mirrors the auto-prediction + OK/NO approval flow from ppc.py.")

    if gen:
        try:
            queue = _build_prediction_queue(live_rows)
            if not queue:
                st.warning("No eligible BPO for prediction (missing fields or already saved).")
            else:
                st.session_state.prediction_queue = queue[1:]
                st.session_state.pending_prediction = queue[0]
        except Exception as exc:
            st.error(f"Prediction generation failed: {exc}")

    pending = st.session_state.get("pending_prediction")
    if not pending:
        st.info("No pending predictions. Click 'Generate predictions'.")
    else:
        po_number = str(pending.get("po_number", ""))
        pred_line = str(pending.get("pred_line", ""))
        pred_days = int(pending.get("pred_days", 0) or 0)
        top3 = pending.get("top_line_recos", [])
        top3_text = ", ".join([f"{item['line']} ({item['score'] * 100:.1f}%)" for item in top3])
        pred_end_date = (datetime.now() + timedelta(days=pred_days)).strftime("%d-%b-%Y") if pred_days > 0 else "N/A"

        st.success(
            f"Now reviewing: {po_number} | Recommended Line: {pred_line} | Top 3 Lines: {top3_text} | "
            f"Estimated Days: {pred_days} | Expected End: {pred_end_date}"
        )
        st.dataframe(pd.DataFrame([pending.get("pred_row", {})]), use_container_width=True)

        ok_col, no_col, meta_col = st.columns([1, 1, 3])
        with ok_col:
            ok = st.button("OK (Save)", type="primary", use_container_width=True)
        with no_col:
            no = st.button("NO (Discard)", use_container_width=True)
        with meta_col:
            remaining = st.session_state.get("prediction_queue") or []
            st.caption(f"Remaining queue: {len(remaining)}")

        def _advance_queue() -> None:
            queue_rows = st.session_state.get("prediction_queue") or []
            if queue_rows:
                st.session_state.pending_prediction = queue_rows[0]
                st.session_state.prediction_queue = queue_rows[1:]
            else:
                st.session_state.pending_prediction = None
                st.session_state.prediction_queue = []

        if ok:
            try:
                pending_row = pending.get("pred_row", {})
                ppc_dash._upsert_saved_plan_row(pending_row)
                ppc_dash._persist_saved_plans()
                _advance_queue()
                st.rerun()
            except Exception as exc:
                st.error(f"Save failed: {exc}")

        if no:
            _advance_queue()
            st.rerun()


elif page == "Order Tracker":
    st.subheader("🧭 Order Tracker")
    query = st.text_input("Search by BPO Number, customer, style, or line")

    if not query.strip():
        st.info("Waiting for search")
        st.stop()

    q = query.strip().lower()
    orders_to_search = list(getattr(ppc_dash, "orders", [])) + ppc_dash._saved_plans_as_orders()
    matched_orders = []
    for order in orders_to_search:
        search_text = " ".join(
            [
                str(order.get("bpo", order.get("po", ""))),
                str(order.get("customer", "")),
                str(order.get("style", "")),
                str(order.get("line", "")),
            ]
        ).lower()
        if q in search_text:
            matched_orders.append(order)

    if not matched_orders:
        st.warning("No results")
        st.stop()

    st.success(f"Found {len(matched_orders)} match(es)")
    matched_df = pd.DataFrame(matched_orders)
    st.dataframe(matched_df, use_container_width=True, height=420)

    pick = st.selectbox(
        "Select order to view stages",
        [str(o.get("bpo", o.get("po", ""))) for o in matched_orders],
    )
    selected = next((o for o in matched_orders if str(o.get("bpo", o.get("po", ""))) == pick), None)
    if selected is None:
        st.stop()
    stages = selected.get("stages") or []
    if stages:
        st.markdown("#### Stages")
        st.dataframe(pd.DataFrame(stages), use_container_width=True)
    else:
        st.info("No stages for this order.")


else:
    st.stop()
