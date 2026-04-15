import io

import pandas as pd
import streamlit as st


st.set_page_config(page_title="PPC Planner", layout="wide")

st.title("PPC Planner")
st.caption("Streamlit entrypoint. Upload private Excel files at runtime; do not commit them to Git.")

with st.sidebar:
    st.header("Inputs")
    uploaded = st.file_uploader(
        "Upload Excel (.xlsx)",
        type=["xlsx"],
        accept_multiple_files=False,
        help="Your Excel stays in the session memory unless you explicitly save it.",
    )


@st.cache_data(show_spinner=False)
def _load_excel(file_bytes: bytes) -> tuple[list[str], dict[str, pd.DataFrame]]:
    buffer = io.BytesIO(file_bytes)
    xl = pd.ExcelFile(buffer)
    sheets: dict[str, pd.DataFrame] = {}
    for sheet in xl.sheet_names:
        try:
            sheets[sheet] = pd.read_excel(buffer, sheet_name=sheet)
        except Exception:
            continue
    return xl.sheet_names, sheets


if not uploaded:
    st.info("Upload an Excel file from the sidebar to begin.")
    st.stop()

file_bytes = uploaded.getvalue()
sheet_names, sheets = _load_excel(file_bytes)

col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.subheader("Workbook")
    st.write({"filename": uploaded.name, "size_kb": round(len(file_bytes) / 1024, 1)})
    st.write("Sheets:")
    st.write(sheet_names)

with col2:
    st.subheader("Preview")
    sheet = st.selectbox("Sheet", sheet_names)
    df = sheets.get(sheet)
    if df is None or df.empty:
        st.warning("No preview available for this sheet.")
    else:
        st.dataframe(df.head(200), use_container_width=True)
