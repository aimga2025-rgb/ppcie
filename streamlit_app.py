import hashlib
import io
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


st.set_page_config(page_title="MG PPC Dashboard", layout="wide")


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


def _write_private_upload_to_temp(uploaded_file, suffix: str) -> Path:
    file_bytes = uploaded_file.getvalue()
    digest = hashlib.sha1(file_bytes).hexdigest()[:12]
    tmp_dir = Path(tempfile.gettempdir()) / "ppc_private_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / f"upload_{digest}{suffix}"
    out_path.write_bytes(file_bytes)
    return out_path


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

with st.sidebar:
    st.header("Inputs")
    page = st.radio("Navigation", ["Dashboard", "PPC Planner", "Order Tracker"], index=0)
    uploaded_files = st.file_uploader(
        "Upload files (Excel/CSV)",
        type=["xlsx", "csv"],
        accept_multiple_files=True,
        help="Upload your private Excel at runtime (do not commit to Git).",
    )

inputs = _detect_inputs(uploaded_files)
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
    if sewing_ok and inputs.get("sewing_plan") is not None:
        plan_path = _write_private_upload_to_temp(inputs["sewing_plan"], ".xlsx")
        ppc_dash.EXCEL_PATH = Path(plan_path)
        try:
            ppc_dash._load_sewing_plan_df.cache_clear()
        except Exception:
            pass
        try:
            ppc_dash._lookup_inputs_by_po.cache_clear()
        except Exception:
            pass

    if inputs.get("skill_matrix") is not None:
        skill_path = _write_private_upload_to_temp(inputs["skill_matrix"], ".xlsx")
        ppc_dash.SKILL_MATRIX_FILE_HINT = str(skill_path)
        # Clear cached skill matrix loads if present.
        for name in ("_load_skill_matrix_normalized", "_skill_matrix_resources_for_line"):
            fn = getattr(ppc_dash, name, None)
            if fn is not None and hasattr(fn, "cache_clear"):
                try:
                    fn.cache_clear()
                except Exception:
                    pass

    if inputs.get("plan_history") is not None:
        # If user uploads a plan history CSV, save it to the default path used by ppc.py
        # so both Streamlit and ppc.py see the same history file structure.
        try:
            ppc_dash.PLAN_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            ppc_dash.PLAN_HISTORY_PATH.write_bytes(inputs["plan_history"].getvalue())
        except Exception:
            pass


_sync_private_inputs_into_ppc()


if page == "Dashboard":
    st.subheader("📊 Production Dashboard")

    plan_df = _read_saved_plans_csv(str(ppc_dash.PLAN_HISTORY_PATH))
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

    if month_value and "Ex-mill Mnth" in plan_df.columns:
        filtered = plan_df[plan_df["Ex-mill Mnth"].astype(str).str.strip() == str(month_value).strip()]
        if filtered.empty:
            filtered = plan_df
    else:
        filtered = plan_df

    if search_bpo:
        q = str(search_bpo).strip().lower()
        bpo_col = "BPO Number" if "BPO Number" in filtered.columns else ("PO#" if "PO#" in filtered.columns else None)
        if bpo_col:
            filtered = filtered[filtered[bpo_col].astype(str).str.lower().str.contains(q, na=False)]

    k1, k2, k3, k4 = _kpis_from_df(filtered if not filtered.empty else plan_df)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active Lines", k1)
    m2.metric("Active Orders", k2)
    m3.metric("Avg Efficiency", k3)
    m4.metric("Total Plan Qty", k4)

    st.markdown("#### All Month Plans")
    if filtered.empty:
        st.info("No saved plans yet. Approve predictions in 'PPC Planner' to create plan history.")
    else:
        st.dataframe(filtered, use_container_width=True, height=520)


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
