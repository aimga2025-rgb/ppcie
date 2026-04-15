import io
from typing import Any

import pandas as pd
import streamlit as st


st.set_page_config(page_title="PPC Planner", layout="wide")

st.title("PPC Planner")
st.caption("Streamlit entrypoint. Upload private Excel files at runtime; do not commit them to Git.")

with st.sidebar:
    st.header("Inputs")

    uploaded_files = st.file_uploader(
        "Upload files (Excel/CSV)",
        type=["xlsx", "csv"],
        accept_multiple_files=True,
        help="Tip: you can select multiple files at once. Files remain in session memory unless you explicitly save them.",
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
        df = _load_excel_sheet(xlsx_file.getvalue(), REQUIRED_SEWING_SHEET, skiprows=2)
    except Exception as exc:
        return False, f"Could not read sheet '{REQUIRED_SEWING_SHEET}': {type(exc).__name__}: {exc}", None

    missing = [c for c in REQUIRED_SEWING_COLS if c not in df.columns]
    if missing:
        return False, f"Missing required columns: {', '.join(missing)}", df
    return True, "OK", df


if not uploaded_files:
    st.info("Upload the required Excel workbook(s) from the sidebar to begin.")
    st.stop()

inputs = _detect_inputs(uploaded_files)
sewing_ok, sewing_msg, sewing_df = _validate_sewing_plan(inputs["sewing_plan"])

st.subheader("What you need to upload (based on your `ppc.py`)")
st.write(
    {
        "Required": [
            "1) Sewing Loading Plan workbook (.xlsx) containing sheet 'Sewing Loading Plan'",
        ],
        "Optional": [
            "2) Skill Matrix workbook (.xlsx) (for resource recommendation)",
            "3) Saved plan history (.csv) if you want to start with existing plans",
            "4) Holidays CSV (only if you want to override the bundled one)",
        ],
    }
)

status_col1, status_col2 = st.columns(2)
with status_col1:
    st.markdown("**Detected inputs**")
    st.write(
        {
            "sewing_plan": getattr(inputs["sewing_plan"], "name", None),
            "skill_matrix": getattr(inputs["skill_matrix"], "name", None),
            "plan_history": getattr(inputs["plan_history"], "name", None),
            "holidays": getattr(inputs["holidays"], "name", None),
            "others": [getattr(x, "name", "") for x in inputs["others"]],
        }
    )

with status_col2:
    st.markdown("**Validation**")
    if sewing_ok:
        st.success(f"Sewing plan: {sewing_msg}")
    else:
        st.error(f"Sewing plan: {sewing_msg}")

st.divider()

preview_tabs = st.tabs(["Sewing Plan Preview", "Any File Preview"])

with preview_tabs[0]:
    if not sewing_ok or sewing_df is None:
        st.warning("Upload a valid Sewing Loading Plan workbook to preview.")
    else:
        st.dataframe(sewing_df.head(200), use_container_width=True)

with preview_tabs[1]:
    file_names = [getattr(f, "name", "") for f in uploaded_files]
    pick = st.selectbox("File", file_names)
    picked = next((f for f in uploaded_files if getattr(f, "name", "") == pick), None)
    if picked is None:
        st.stop()
    suffix = pick.lower().split(".")[-1] if "." in pick else ""
    if suffix == "csv":
        try:
            df = _load_csv(picked.getvalue())
            st.dataframe(df.head(200), use_container_width=True)
        except Exception as exc:
            st.error(f"Could not read CSV: {type(exc).__name__}: {exc}")
    elif suffix == "xlsx":
        try:
            sheets = _excel_sheet_names(picked.getvalue())
            sheet = st.selectbox("Sheet", sheets)
            df = _load_excel_sheet(picked.getvalue(), sheet)
            st.dataframe(df.head(200), use_container_width=True)
        except Exception as exc:
            st.error(f"Could not read Excel: {type(exc).__name__}: {exc}")
    else:
        st.info("Preview not supported for this file type.")
