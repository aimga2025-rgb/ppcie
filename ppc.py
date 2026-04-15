import dash
from dash import html, Input, Output, State, callback, dcc, no_update, ALL
import dash_bootstrap_components as dbc
import pandas as pd
try:
    import joblib
except Exception:
    joblib = None

try:
    import xgboost as xgb
except Exception:
    xgb = None
try:
    from sklearn.preprocessing import LabelEncoder
except Exception:
    LabelEncoder = None
try:
    from sklearn.metrics import mean_absolute_error
except Exception:
    mean_absolute_error = None
from pathlib import Path
from datetime import datetime, timedelta, date
from math import ceil
import json
import os
from functools import lru_cache
import calendar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import threading
import time
from queue import Queue

try:
    import holidays as country_holidays
except Exception:
    country_holidays = None


def _ensure_ml_dependencies() -> list[str]:
    """Best-effort (re)import of optional ML dependencies.

    Dash hot-reload + runtime package installs can leave module-level imports as None.
    This helper allows training/prediction actions to recover without restarting.

    Returns a list of missing dependency names (e.g., ["xgboost", "scikit-learn"]).
    """

    global joblib, xgb, LabelEncoder, mean_absolute_error

    missing: list[str] = []

    if joblib is None:
        try:
            import joblib as _joblib  # type: ignore

            joblib = _joblib
        except Exception:
            missing.append("joblib")

    if xgb is None:
        try:
            import xgboost as _xgb  # type: ignore

            xgb = _xgb
        except Exception:
            missing.append("xgboost")

    sklearn_missing = False
    if LabelEncoder is None:
        try:
            from sklearn.preprocessing import LabelEncoder as _LabelEncoder  # type: ignore

            LabelEncoder = _LabelEncoder
        except Exception:
            sklearn_missing = True

    if mean_absolute_error is None:
        try:
            from sklearn.metrics import mean_absolute_error as _mae  # type: ignore

            mean_absolute_error = _mae
        except Exception:
            sklearn_missing = True

    if sklearn_missing:
        missing.append("scikit-learn")

    # Dedupe while preserving order.
    seen = set()
    unique_missing = []
    for dep in missing:
        if dep in seen:
            continue
        seen.add(dep)
        unique_missing.append(dep)
    return unique_missing

# ================== DATA ==================
orders = [
    {
        "bpo": "KBI-2602-00244",
        "po": "KBI-2602-00244", "customer": "KIABI", "line": "L#1-H", "style": "MGMW18PSLIM",
        "fabric": "NON DENIM, TWILL_315 PEACH BEIGE SIMP...", "wash": "Rinse", "color": "BEIGE SIMP",
        "sam": 12.26, "efficiency": "75%", "capacity": 1703, "planQty": 9319, "balSew": 1612,
        "ppcStatus": "Sewing", "indTarget": "22-Mar-2026", "exMill": "03-Apr-2026",
        "stages": [
            {"name": "BPO Received", "status": "done", "date_completed": "19-Mar-2026", "lead_days": 0},
            {"name": "Fabric Clearance", "status": "done", "date_completed": "22-Mar-2026", "lead_days": 3},
            {"name": "Trims Cleared", "status": "done", "date_completed": "24-Mar-2026", "lead_days": 2},
            {"name": "Induction / Cut", "status": "done", "date_completed": "25-Mar-2026", "lead_days": 1},
            {"name": "Sew Start", "status": "current", "date_started": "27-Mar-2026", "lead_days": 2},
            {"name": "Sew Out", "status": "pending", "date_planned": "03-Apr-2026", "lead_days": 7},
            {"name": "EX-MILL", "status": "pending", "date_planned": "05-Apr-2026", "lead_days": 2}
        ]
    },
    {
        "bpo": "KBI-2602-00252",
        "po": "KBI-2602-00252", "customer": "KIABI", "line": "L#1-H", "style": "MGMW18PSLIM_V2",
        "fabric": "DENIM, TWILL_350", "wash": "Stone", "color": "BLUE",
        "sam": 10.5, "efficiency": "78%", "capacity": 1800, "planQty": 2870, "balSew": 300,
        "ppcStatus": "Induction Cut", "indTarget": "22-Mar-2026", "exMill": "10-Apr-2026",
        "stages": [
            {"name": "BPO Received", "status": "done", "date_completed": "20-Mar-2026", "lead_days": 0},
            {"name": "Fabric Clearance", "status": "done", "date_completed": "23-Mar-2026", "lead_days": 3},
            {"name": "Trims Cleared", "status": "done", "date_completed": "25-Mar-2026", "lead_days": 2},
            {"name": "Induction / Cut", "status": "current", "date_started": "26-Mar-2026", "lead_days": 1},
            {"name": "Sew Start", "status": "pending", "date_planned": "29-Mar-2026", "lead_days": 3},
            {"name": "Sew Out", "status": "pending", "date_planned": "07-Apr-2026", "lead_days": 9},
            {"name": "EX-MILL", "status": "pending", "date_planned": "10-Apr-2026", "lead_days": 3}
        ]
    },
    {
        "bpo": "TWS-2511-02184",
        "po": "TWS-2511-02184", "customer": "TWO SOON", "line": "L#2 MZ", "style": "SOLID_BASIC",
        "fabric": "COTTON, JERSEY_250", "wash": "Pigment", "color": "BLACK",
        "sam": 8.2, "efficiency": "82%", "capacity": 2100, "planQty": 5150, "balSew": 50,
        "ppcStatus": "Planned", "indTarget": "28-Mar-2026", "exMill": "07-Apr-2026",
        "stages": [
            {"name": "BPO Received", "status": "done", "date_completed": "18-Mar-2026", "lead_days": 0},
            {"name": "Fabric Clearance", "status": "done", "date_completed": "21-Mar-2026", "lead_days": 3},
            {"name": "Trims Cleared", "status": "pending", "date_planned": "26-Mar-2026", "lead_days": 5},
            {"name": "Induction / Cut", "status": "pending", "date_planned": "28-Mar-2026", "lead_days": 2},
            {"name": "Sew Start", "status": "pending", "date_planned": "01-Apr-2026", "lead_days": 4},
            {"name": "Sew Out", "status": "pending", "date_planned": "06-Apr-2026", "lead_days": 5},
            {"name": "EX-MILL", "status": "pending", "date_planned": "07-Apr-2026", "lead_days": 1}
        ]
    }
]

ppc_data = pd.DataFrame([
    {"bpo": "KBI-2602-00244", "po": "KBI-2602-00244", "cust": "KIABI", "inDate": "22-Mar-2026", "line": "L#1-H", "planQty": 9319, "status": "Cutting done", "statusCls": "success", "exMill": "03-Apr-2026"},
    {"bpo": "KBI-2602-00252", "po": "KBI-2602-00252", "cust": "KIABI", "inDate": "22-Mar-2026", "line": "L#1-H", "planQty": 2870, "status": "Cutting done", "statusCls": "success", "exMill": "10-Apr-2026"},
])

# Keep initial dashboard table schema consistent with callback-rendered All Month Plans table.
ppc_data = pd.DataFrame(columns=[
    "SR#", "Line", "Planned Quantity", "Average SAM", "Planned Efficiency",
    "Per day Capacity", "Work Days", "Sundays", "Holiday", "Month Days",
    "Available SAM", "Produced SAM"
])

# ================== AI PLANNER ==================
ROOT_DIR = Path(__file__).resolve().parent
EXCEL_PATH = ROOT_DIR / "data" / "Sewing loading Plan..xlsx"
MODEL_DIR = ROOT_DIR / "data" / "models"
PLAN_HISTORY_PATH = ROOT_DIR / "data" / "saved_plan_history.csv"
MODEL_META_PATH = MODEL_DIR / "ppc_feature_meta.json"
OFFICIAL_HOLIDAYS_PATH = ROOT_DIR / "data" / "pakistan_public_holidays_official.csv"
LIVE_PPC_CACHE_PATH = ROOT_DIR / "data" / "live_planner_cache.json"
LIVE_PPC_ENDPOINT = os.getenv("PPC_LIVE_ENDPOINT", "http://110.38.236.7:7003/ords/ws_apparel/ppc-planner/bpo")
LIVE_PPC_TIMEOUT = int(os.getenv("PPC_LIVE_TIMEOUT", "12"))  # Long enough for the live API to return current-day records
LIVE_PPC_REFRESH_MS = int(os.getenv("PPC_LIVE_REFRESH_MS", "30000"))  # 30 seconds - faster refresh
LIVE_PPC_LOOKBACK_DAYS = int(os.getenv("PPC_LIVE_LOOKBACK_DAYS", "0"))  # 0 days = Only TODAY's data
LIVE_PPC_CACHE_TTL = int(os.getenv("PPC_LIVE_CACHE_TTL", "45"))  # Cache validity in seconds
LIVE_PPC_ONLY_TODAY = True  # Filter to show ONLY today's data (no old records)
LIVE_PPC_LAST_FETCH_TIME = 0  # Track last successful fetch
LIVE_PPC_LAST_SYNC_HASH = None  # Track data changes
LIVE_PPC_BG_FETCH_QUEUE = Queue()  # Background fetch results
STRICT_RESOURCE_AVAILABILITY = os.getenv("PPC_STRICT_RESOURCE_AVAILABILITY", "0").strip().lower() in {"1", "true", "yes", "y"}

# Disable extremely-verbose per-record date logs by default (printing thousands of lines slows Dash callbacks).
DEBUG_DATE_FILTER = os.getenv("PPC_DEBUG_DATE_FILTER", "0").strip().lower() in {"1", "true", "yes", "y"}
DEBUG_DATE_FILTER_LIMIT = int(os.getenv("PPC_DEBUG_DATE_FILTER_LIMIT", "25"))

FEATURES = ["Cstmr", "Style", "Product", "Fabric", "wash Type", "Color", "SAM", "Plan Qty", "Pln Eff Num", "Bal Sew"]
TARGETS = ["Line #", "TotalDays"]
FEATURE_CATEGORICAL_COLS = ["Cstmr", "Style", "Product", "Fabric", "wash Type", "Color"]
CATEGORICAL_COLS = FEATURE_CATEGORICAL_COLS + ["Line #"]
PLAN_NUMBER_FIELDS = ("BPO Number", "PO#", "bpo_number", "po")
SKILL_MATRIX_FILE_HINT = os.getenv("PPC_SKILL_MATRIX_FILE", "")


def _plan_history_signature() -> tuple[int, int]:
    """Reliable change signature for CSV cache invalidation on Windows."""
    if not PLAN_HISTORY_PATH.exists():
        return (0, 0)
    stat = PLAN_HISTORY_PATH.stat()
    mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
    return (mtime_ns, int(stat.st_size))


def _normalize_efficiency(value) -> float | None:
    text = str(value or "").strip().replace("%", "")
    if not text:
        return None
    try:
        eff = float(text)
    except Exception:
        return None
    if eff > 1.5:
        eff = eff / 100.0
    return eff


def _first_non_empty(*values):
    for value in values:
        if pd.isna(value):
            continue
        text = str(value or "").strip()
        if text and text.lower() not in {"nan", "none"}:
            return text
    return ""


def _canonical_text(value) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _line_name_from_sheet_name(sheet_name: str) -> str:
    text = str(sheet_name or "").strip()
    if not text:
        return ""

    norm = _canonical_text(text)
    if "prep" in norm:
        return "Prep Section"

    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return str(int(digits))

    return text


def _find_col_by_aliases(columns, aliases: list[str]):
    alias_norm = {_canonical_text(a) for a in aliases}
    for col in columns:
        if _canonical_text(col) in alias_norm:
            return col
    return None


def _is_truthy_skill_mark(value) -> bool:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "x", "ok"}:
        return True
    if text in {"", "nan", "none", "0", "false", "no", "n"}:
        return False
    # Common symbols used in skill matrices for capability marks.
    return text in {"\u221a", "\u2713", "\u2714"}


def _skill_level_to_score(value) -> float:
    text = str(value or "").strip()
    if not text:
        return 50.0

    num = pd.to_numeric(pd.Series([text]), errors="coerce").iloc[0]
    if pd.notna(num):
        val = float(num)
        if val <= 10:
            val = val * 10.0
        elif val <= 1.5:
            val = val * 100.0
        return max(0.0, min(100.0, val))

    key = _canonical_text(text)
    mapping = {
        "a": 95.0,
        "aplus": 98.0,
        "b": 80.0,
        "c": 65.0,
        "d": 50.0,
        "expert": 95.0,
        "advanced": 85.0,
        "intermediate": 70.0,
        "beginner": 45.0,
        "novice": 35.0,
        "high": 85.0,
        "medium": 65.0,
        "low": 45.0,
        "trained": 75.0,
        "untrained": 25.0,
    }
    return mapping.get(key, 50.0)


@lru_cache(maxsize=1)
def _load_skill_matrix_df() -> pd.DataFrame:
    data_dir = ROOT_DIR / "data"
    if not data_dir.exists():
        return pd.DataFrame()

    preferred_path = data_dir / SKILL_MATRIX_FILE_HINT if SKILL_MATRIX_FILE_HINT else None
    if preferred_path and preferred_path.exists():
        skill_file = preferred_path
    else:
        matches = sorted(p for p in data_dir.glob("*.xlsx") if "skill" in p.name.lower() and "matrix" in p.name.lower())
        if not matches:
            return pd.DataFrame()
        skill_file = matches[0]

    try:
        xl = pd.ExcelFile(skill_file)
    except Exception:
        return pd.DataFrame()

    normalized_frames = []
    for sheet_name in xl.sheet_names:
        fallback_norm = _extract_matrix_style_skill_rows(skill_file, sheet_name)
        if not fallback_norm.empty:
            normalized_frames.append(fallback_norm)

        try:
            raw = pd.read_excel(skill_file, sheet_name=sheet_name)
        except Exception:
            continue

        if raw.empty:
            continue

        raw.columns = [str(col).strip() for col in raw.columns]
        resource_col = _find_col_by_aliases(raw.columns, [
            "resource", "resource name", "operator", "operator name", "employee", "employee name", "worker", "name", "manpower",
        ])
        if not resource_col:
            continue

        line_col = _find_col_by_aliases(raw.columns, ["line", "line #", "line#", "line no", "line number", "line allocation"])
        resource_code_col = _find_col_by_aliases(raw.columns, ["resource code", "code", "employee code", "emp code", "operator code", "id"])
        operation_col = _find_col_by_aliases(raw.columns, ["operation", "operation name", "op", "process", "task"])
        efficiency_col = _find_col_by_aliases(raw.columns, ["efficiency", "eff", "eff %", "skill", "skill score", "score", "rating"])
        skill_level_col = _find_col_by_aliases(raw.columns, ["skill level", "skilllevel", "level", "proficiency", "grade", "competency"])
        availability_col = _find_col_by_aliases(raw.columns, ["availability", "status", "present", "active", "is available"])
        current_line_col = _find_col_by_aliases(raw.columns, ["current line", "assigned line", "working line", "running line", "line current"])
        style_col = _find_col_by_aliases(raw.columns, ["style", "style number", "style no", "item"])
        customer_col = _find_col_by_aliases(raw.columns, ["customer", "cstmr", "buyer"])

        norm = pd.DataFrame()
        norm["resource_name"] = raw[resource_col].astype(str).str.strip()
        norm = norm[norm["resource_name"] != ""]
        norm = norm[norm["resource_name"].str.lower() != "nan"]
        if norm.empty:
            continue

        norm["resource_code"] = raw[resource_code_col].astype(str).str.strip() if resource_code_col else ""
        norm["line_name"] = raw[line_col].astype(str).str.strip() if line_col else ""
        norm["operation_name"] = raw[operation_col].astype(str).str.strip() if operation_col else ""
        norm["availability"] = raw[availability_col].astype(str).str.strip() if availability_col else ""
        norm["current_line"] = raw[current_line_col].astype(str).str.strip() if current_line_col else ""
        norm["style_ref"] = raw[style_col].astype(str).str.strip() if style_col else ""
        norm["customer_ref"] = raw[customer_col].astype(str).str.strip() if customer_col else ""

        if skill_level_col:
            norm["skill_level_score"] = raw[skill_level_col].apply(_skill_level_to_score)
        else:
            norm["skill_level_score"] = 50.0

        if efficiency_col:
            eff_num = pd.to_numeric(raw[efficiency_col], errors="coerce").fillna(50)
            eff_num = eff_num.apply(lambda x: float(x) * 100.0 if float(x) <= 1.5 else float(x))
            norm["efficiency_score"] = eff_num.clip(lower=0, upper=100)
        else:
            norm["efficiency_score"] = 50.0

        normalized_frames.append(norm)

    if not normalized_frames:
        return pd.DataFrame()

    skill_df = pd.concat(normalized_frames, ignore_index=True)
    for col in ["resource_name", "resource_code", "line_name", "operation_name", "availability", "current_line", "style_ref", "customer_ref"]:
        skill_df[col] = skill_df[col].fillna("").astype(str).str.strip()
    skill_df["efficiency_score"] = pd.to_numeric(skill_df["efficiency_score"], errors="coerce").fillna(50.0)
    skill_df["skill_level_score"] = pd.to_numeric(skill_df["skill_level_score"], errors="coerce").fillna(50.0).clip(lower=0.0, upper=100.0)
    skill_df["line_match_key"] = skill_df["line_name"].astype(str).apply(_line_match_key)
    skill_df["line_digits"] = skill_df["line_name"].astype(str).apply(_line_digits)
    skill_df = skill_df.drop_duplicates(subset=["resource_name", "line_name", "operation_name"], keep="first")
    return skill_df


def _extract_matrix_style_skill_rows(skill_file: Path, sheet_name: str) -> pd.DataFrame:
    try:
        raw = pd.read_excel(skill_file, sheet_name=sheet_name, header=None)
    except Exception:
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    header_row_idx = None
    name_col_idx = None
    code_col_idx = None
    skill_col_idx = None
    line_col_idx = None
    fallback_line = _line_name_from_sheet_name(sheet_name)

    for i in range(min(80, len(raw))):
        row_vals = [str(v or "").strip() for v in raw.iloc[i].tolist()]
        row_norm = [_canonical_text(v) for v in row_vals]
        if not any(v for v in row_norm):
            continue

        for j, val in enumerate(row_norm):
            if val in {"name", "operatorname", "employeename", "resourcename", "workername"}:
                name_col_idx = j
            elif val in {"employcode", "employeecode", "code", "operatorcode", "empcode", "id"}:
                code_col_idx = j
            elif val in {"skilllevel", "level", "proficiency", "grade", "competency"}:
                skill_col_idx = j
            elif val in {"lineno", "line", "linenumber", "lineno."}:
                line_col_idx = j

        # Some sheets do not have an explicit line column; use sheet name as fallback line.
        if name_col_idx is not None and (line_col_idx is not None or fallback_line):
            header_row_idx = i
            break

    if header_row_idx is None or name_col_idx is None:
        return pd.DataFrame()

    header_norm = [_canonical_text(str(v or "").strip()) for v in raw.iloc[header_row_idx].tolist()]

    # Optional helper row: SAM values are commonly on the next row after header.
    sam_row_vals = []
    sam_row_idx = None
    for probe_i in range(max(0, header_row_idx), min(len(raw), header_row_idx + 4)):
        probe_vals = [str(v or "").strip() for v in raw.iloc[probe_i].tolist()]
        probe_norm = [_canonical_text(v) for v in probe_vals]
        if any(v == "sam" for v in probe_norm):
            sam_row_idx = probe_i
            sam_row_vals = probe_vals
            break

    level_to_score = {
        "i": 65.0,
        "ii": 78.0,
        "iii": 90.0,
        "iv": 97.0,
        "v": 100.0,
        "a": 95.0,
        "b": 80.0,
        "c": 65.0,
    }
    data_rows = []

    for i in range(header_row_idx + 1, len(raw)):
        row = raw.iloc[i]
        first_text = str(row.iloc[0] or "").strip().lower()
        if first_text.startswith("no. of operators"):
            break

        resource_name = str(row.iloc[name_col_idx] or "").strip()
        if not resource_name or resource_name.lower() in {"nan", "none", "name"}:
            continue

        resource_code = ""
        if code_col_idx is not None:
            resource_code = str(row.iloc[code_col_idx] or "").strip()

        line_name = ""
        if line_col_idx is not None:
            line_name = str(row.iloc[line_col_idx] or "").strip()
        if not line_name or line_name.lower() in {"nan", "none"}:
            line_name = fallback_line

        skill_text = ""
        if skill_col_idx is not None:
            skill_text = str(row.iloc[skill_col_idx] or "").strip()
        parsed_skill = _skill_level_to_score(skill_text) if skill_text else None

        # Derive capability profile across operation columns.
        tick_count = 0
        marked_level_scores = []
        marked_sam_values = []
        for col_idx in range(len(row)):
            if col_idx in {name_col_idx, code_col_idx, skill_col_idx, line_col_idx}:
                continue
            head_tag = header_norm[col_idx] if col_idx < len(header_norm) else ""
            if head_tag in {"", "srno", "skillmatrix"}:
                continue
            if _is_truthy_skill_mark(row.iloc[col_idx]):
                tick_count += 1
                level_text = str(raw.iloc[header_row_idx, col_idx] or "").strip().lower().replace(" ", "")
                marked_level_scores.append(level_to_score.get(level_text, 72.0))
                if sam_row_idx is not None and col_idx < len(sam_row_vals):
                    sam_num = pd.to_numeric(pd.Series([sam_row_vals[col_idx]]), errors="coerce").iloc[0]
                    if pd.notna(sam_num):
                        marked_sam_values.append(float(sam_num))

        avg_mark_skill = float(sum(marked_level_scores) / len(marked_level_scores)) if marked_level_scores else None
        if parsed_skill is None and avg_mark_skill is None:
            skill_score = 50.0
        elif parsed_skill is None:
            skill_score = float(avg_mark_skill)
        elif avg_mark_skill is None:
            skill_score = float(parsed_skill)
        else:
            skill_score = max(float(parsed_skill), float(avg_mark_skill))

        breadth_factor = min(1.0, float(tick_count) / 6.0)
        complexity_factor = min(1.0, max(0.0, float(skill_score) / 100.0))
        if marked_sam_values:
            sam_factor = min(1.0, sum(marked_sam_values) / 4.0)
        else:
            sam_factor = breadth_factor
        efficiency_score = (35.0 + (30.0 * complexity_factor) + (35.0 * max(breadth_factor, sam_factor)))
        efficiency_score = max(0.0, min(100.0, efficiency_score))

        operation_name = ""
        data_rows.append(
            {
                "resource_name": resource_name,
                "resource_code": resource_code,
                "line_name": line_name,
                "operation_name": operation_name,
                "availability": "",
                "current_line": "",
                "style_ref": "",
                "customer_ref": "",
                "efficiency_score": efficiency_score,
                "skill_level_score": skill_score,
            }
        )

    if not data_rows:
        return pd.DataFrame()
    return pd.DataFrame(data_rows)


def _is_resource_available(availability_text: str) -> bool:
    text = _canonical_text(availability_text)
    if not text:
        return True

    unavailable_tokens = ["absent", "leave", "off", "unavailable", "busy", "allocated", "notavailable"]
    available_tokens = ["available", "idle", "free", "present", "yes"]

    if any(token in text for token in unavailable_tokens):
        return False
    if any(token in text for token in available_tokens):
        return True
    return True


def _recommend_resources(pred_line: str, style: str | None = None, customer: str | None = None, operation: str | None = None, top_n: int = 3) -> list[dict]:
    skill_df = _load_skill_matrix_df()
    if skill_df.empty:
        return []

    pred_line_norm = _canonical_text(pred_line)
    style_norm = _canonical_text(style)
    customer_norm = _canonical_text(customer)
    operation_norm = _canonical_text(operation)

    scored = []
    for _, row in skill_df.iterrows():
        availability = str(row.get("availability", ""))
        current_line = str(row.get("current_line", "")).strip()

        # Skip unavailable/busy resources; avoid already assigned line resources.
        if not _is_resource_available(availability):
            continue

        resource_name = str(row.get("resource_name", "")).strip()
        if not resource_name:
            continue

        resource_code = str(row.get("resource_code", "")).strip()
        line_name = str(row.get("line_name", "")).strip()
        operation_name = str(row.get("operation_name", "")).strip()
        style_ref = str(row.get("style_ref", "")).strip()
        customer_ref = str(row.get("customer_ref", "")).strip()
        efficiency = float(row.get("efficiency_score", 50.0) or 50.0)
        skill_level = float(row.get("skill_level_score", 50.0) or 50.0)

        line_match = 100.0 if (_canonical_text(line_name) == pred_line_norm and pred_line_norm) else 0.0
        base_score = (0.50 * line_match) + (0.30 * skill_level) + (0.20 * efficiency)
        compat_bonus = 0.0
        reasons = []

        if line_match > 0:
            reasons.append("line-match")
        else:
            reasons.append("line-mismatch")

        current_line_norm = _canonical_text(current_line)
        if current_line_norm and current_line_norm not in {"", "nan", "none"}:
            if current_line_norm == pred_line_norm:
                compat_bonus += 2.0
                reasons.append("already-on-line")
            else:
                compat_bonus -= 8.0
                reasons.append("currently-assigned")

        if operation_norm and _canonical_text(operation_name) == operation_norm:
            compat_bonus += 5.0
            reasons.append("operation-match")

        if style_norm and _canonical_text(style_ref) and style_norm in _canonical_text(style_ref):
            compat_bonus += 3.0
            reasons.append("style-match")

        if customer_norm and _canonical_text(customer_ref) and customer_norm in _canonical_text(customer_ref):
            compat_bonus += 2.0
            reasons.append("customer-match")

        score = max(0.0, min(100.0, base_score + compat_bonus))
        reasons.append(f"skill={skill_level:.0f}%")
        reasons.append(f"eff={efficiency:.0f}%")

        scored.append(
            {
                "resource": resource_name,
                "resource_code": resource_code,
                "line": line_name,
                "operation": operation_name,
                "skill_level": round(skill_level, 1),
                "efficiency": round(efficiency, 1),
                "score": round(score, 2),
                "reason": ", ".join(reasons),
            }
        )

    if not scored:
        return []

    # Keep highest score per resource, then return top N.
    best_per_resource = {}
    for item in scored:
        key = _canonical_text(item["resource"] or item.get("resource_code", ""))
        if key not in best_per_resource:
            best_per_resource[key] = item
            continue

        old = best_per_resource[key]
        new_key = (float(item["score"]), float(item.get("skill_level", 0.0)), float(item.get("efficiency", 0.0)))
        old_key = (float(old["score"]), float(old.get("skill_level", 0.0)), float(old.get("efficiency", 0.0)))
        if new_key > old_key:
            best_per_resource[key] = item

    ranked = sorted(
        best_per_resource.values(),
        key=lambda x: (
            -float(x.get("score", 0.0)),
            -float(x.get("skill_level", 0.0)),
            -float(x.get("efficiency", 0.0)),
            str(x.get("resource_code", "")),
            str(x.get("resource", "")),
        ),
    )[: max(1, int(top_n))]
    for idx, item in enumerate(ranked, start=1):
        item["rank"] = idx
    return ranked


def _line_match_key(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""

    canonical = _canonical_text(text)
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return f"{canonical}|{digits}"
    return canonical


def _line_values_match(left: str, right: str) -> bool:
    left_key = _line_match_key(left)
    right_key = _line_match_key(right)
    if not left_key or not right_key:
        return False

    if left_key == right_key:
        return True

    left_digits = left_key.split("|")[-1] if "|" in left_key else ""
    right_digits = right_key.split("|")[-1] if "|" in right_key else ""
    return bool(left_digits and right_digits and left_digits == right_digits)


def _line_digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


@lru_cache(maxsize=256)
def _get_skill_matrix_resources_for_line_cached(line_key: str, line_digits: str) -> pd.DataFrame:
    skill_df = _load_skill_matrix_df()
    if skill_df.empty or "line_name" not in skill_df.columns:
        return pd.DataFrame()

    # Vectorized matching is much faster than row-wise apply for large skill matrices.
    exact_mask = skill_df["line_match_key"].astype(str) == str(line_key)
    if line_digits:
        digits_mask = skill_df["line_digits"].astype(str) == str(line_digits)
        matched = skill_df[exact_mask | digits_mask].copy()
    else:
        matched = skill_df[exact_mask].copy()

    if matched.empty:
        return pd.DataFrame()

    for col in ["resource_name", "resource_code", "line_name", "operation_name", "availability", "current_line", "style_ref", "customer_ref"]:
        if col not in matched.columns:
            matched[col] = ""

    matched["resource_name"] = matched["resource_name"].astype(str).str.strip()
    matched = matched[matched["resource_name"] != ""]
    if matched.empty:
        return pd.DataFrame()

    grouped = (
        matched
        .groupby(["resource_name", "resource_code", "line_name"], as_index=False)
        .agg(
            efficiency_score=("efficiency_score", "max"),
            skill_level_score=("skill_level_score", "max"),
            availability=("availability", lambda s: next((str(v).strip() for v in s if str(v).strip()), "")),
            current_line=("current_line", lambda s: next((str(v).strip() for v in s if str(v).strip()), "")),
            operation_name=("operation_name", lambda s: next((str(v).strip() for v in s if str(v).strip()), "")),
        )
        .sort_values(by=["resource_name", "resource_code"], ascending=[True, True])
    )
    return grouped


def _get_skill_matrix_resources_for_line(line_name: str) -> pd.DataFrame:
    line_key = _line_match_key(line_name)
    if not line_key:
        return pd.DataFrame()

    line_digits = _line_digits(line_name)
    return _get_skill_matrix_resources_for_line_cached(line_key, line_digits).copy()


def _availability_state(value: str) -> str:
    text = _canonical_text(value)
    if not text:
        return "unknown"

    unavailable_tokens = {
        "unavailable", "absent", "leave", "off", "holiday", "sick", "inactive", "notavailable", "notpresent",
    }
    available_tokens = {
        "available", "present", "active", "on", "working", "yes", "y",
    }

    if text in unavailable_tokens:
        return "unavailable"
    if text in available_tokens:
        return "available"
    return "unknown"


def _get_line_active_resources(line_name: str, capacity: int = 58) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return active resources (up to capacity), reserve resources, and availability stats for a line."""
    resources_df = _get_skill_matrix_resources_for_line(line_name)
    if resources_df.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "capacity": int(capacity),
            "mapped_count": 0,
            "available_count": 0,
            "unavailable_count": 0,
            "unknown_count": 0,
            "active_count": 0,
            "reserve_count": 0,
            "shortage_count": int(capacity),
        }

    pool = resources_df.copy()
    pool["availability_state"] = pool["availability"].astype(str).apply(_availability_state)
    has_explicit_availability = bool(((pool["availability_state"] == "available") | (pool["availability_state"] == "unavailable")).any())
    pool["_score"] = (
        pd.to_numeric(pool.get("skill_level_score", 0), errors="coerce").fillna(0) * 0.6
        + pd.to_numeric(pool.get("efficiency_score", 0), errors="coerce").fillna(0) * 0.4
    )

    if STRICT_RESOURCE_AVAILABILITY:
        available_pool = pool[pool["availability_state"] == "available"].copy()
    else:
        available_pool = pool[pool["availability_state"] != "unavailable"].copy()
    available_pool = available_pool.sort_values(
        by=["availability_state", "_score", "skill_level_score", "efficiency_score", "resource_code", "resource_name"],
        ascending=[True, False, False, False, True, True],
    )

    cap = max(1, int(capacity))
    active_df = available_pool.head(cap).copy()
    reserve_df = available_pool.iloc[cap:].copy()

    stats = {
        "capacity": cap,
        "mapped_count": int(len(pool)),
        "available_count": int((pool["availability_state"] == "available").sum()),
        "unavailable_count": int((pool["availability_state"] == "unavailable").sum()),
        "unknown_count": int((pool["availability_state"] == "unknown").sum()),
        "active_count": int(len(active_df)),
        "reserve_count": int(len(reserve_df)),
        "shortage_count": int(max(0, cap - len(active_df))),
        "has_explicit_availability": has_explicit_availability,
        "strict_availability": bool(STRICT_RESOURCE_AVAILABILITY),
    }
    return active_df, reserve_df, stats


def train_ai_models(excel_path: Path):
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")
    missing = _ensure_ml_dependencies()
    if missing or xgb is None or joblib is None or LabelEncoder is None or mean_absolute_error is None:
        deps = ", ".join(missing or ["xgboost", "scikit-learn", "joblib"])
        raise RuntimeError(
            f"ML dependencies are unavailable in this environment (missing/import-failed: {deps}). "
            "Install xgboost and scikit-learn to train models."
        )

    df = pd.read_excel(excel_path, sheet_name="Sewing Loading Plan", skiprows=2)
    required_cols = ["Cstmr", "Style", "SAM", "Plan Qty", "Line #", "Strt Sw Out Dt", "End Sew Date"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing columns in Excel: {', '.join(missing_cols)}")

    for optional_col in ["Product", "Old/New", "Fabric", "wash Type", "Color", "Pln Eff %", "Bal Sew", "Ttl Stch"]:
        if optional_col not in df.columns:
            df[optional_col] = None

    # Keep Product usable with fallback order: Product -> Old/New -> New
    df["Product"] = df.apply(lambda r: _first_non_empty(r.get("Product"), r.get("Old/New"), "New"), axis=1)

    # Normalize categorical features for cleaner encoding.
    df["Cstmr"] = df["Cstmr"].astype(str).str.strip().str.upper()
    df["Style"] = df["Style"].astype(str).str.strip()
    df["Product"] = df["Product"].astype(str).str.strip().str.title()
    df["Fabric"] = df["Fabric"].astype(str).str.strip().str.upper().replace("", "UNKNOWN")
    df["wash Type"] = df["wash Type"].astype(str).str.strip().str.title().replace("", "Unknown")
    df["Color"] = df["Color"].astype(str).str.strip().str.upper().replace("", "UNKNOWN")
    df["Line #"] = df["Line #"].astype(str).str.strip().str.upper()

    df["SAM"] = pd.to_numeric(df["SAM"], errors="coerce")
    df["Plan Qty"] = pd.to_numeric(df["Plan Qty"], errors="coerce")
    df["Bal Sew"] = pd.to_numeric(df["Bal Sew"], errors="coerce")
    ttl_stch_numeric = pd.to_numeric(df["Ttl Stch"], errors="coerce")
    fallback_bal_sew = (df["Plan Qty"] - ttl_stch_numeric).clip(lower=0)
    df["Bal Sew"] = df["Bal Sew"].where(df["Bal Sew"].notna(), fallback_bal_sew)

    df["Pln Eff Num"] = df["Pln Eff %"].apply(_normalize_efficiency)
    default_eff = pd.to_numeric(df["Pln Eff Num"], errors="coerce").dropna()
    default_eff_value = float(default_eff.median()) if not default_eff.empty else 0.75
    df["Pln Eff Num"] = pd.to_numeric(df["Pln Eff Num"], errors="coerce").fillna(default_eff_value)

    df["Strt Sw Out Dt"] = pd.to_datetime(df["Strt Sw Out Dt"], errors="coerce")
    df["End Sew Date"] = pd.to_datetime(df["End Sew Date"], errors="coerce")
    df["TotalDays"] = (df["End Sew Date"] - df["Strt Sw Out Dt"]).dt.days

    df_ml = df[FEATURES + TARGETS].dropna().copy()
    if df_ml.empty:
        raise ValueError("No usable rows after preprocessing. Check date and feature columns.")

    # Filter unrealistic rows to improve model quality.
    df_ml = df_ml[(df_ml["SAM"] > 0) & (df_ml["Plan Qty"] > 0) & (df_ml["TotalDays"] > 0)]
    if df_ml.empty:
        raise ValueError("No valid training rows after quality filtering (SAM, Plan Qty, TotalDays).")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    encoders = {}
    for col in CATEGORICAL_COLS:
        le = LabelEncoder()
        df_ml[col] = le.fit_transform(df_ml[col].astype(str).str.strip())
        encoders[col] = le
        joblib.dump(le, MODEL_DIR / f"{col}_ppc_encoder.pkl")

    X = df_ml[FEATURES]
    y_line = df_ml["Line #"]
    y_days = df_ml["TotalDays"]

    model_line = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=7,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        eval_metric="mlogloss",
        random_state=42,
    )
    model_line.fit(X, y_line)
    model_line.save_model(str(MODEL_DIR / "ppc_line_model.json"))

    model_days = xgb.XGBRegressor(
        n_estimators=300,
        max_depth=7,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_lambda=1.0,
        objective="reg:squarederror",
        random_state=42,
    )
    model_days.fit(X, y_days)
    model_days.save_model(str(MODEL_DIR / "ppc_days_model.json"))

    # Persist feature defaults for robust inference when inputs are missing.
    defaults = {}
    for feature in FEATURES:
        if feature in FEATURE_CATEGORICAL_COLS:
            mode_series = df_ml[feature].mode(dropna=True)
            defaults[feature] = str(mode_series.iloc[0]) if not mode_series.empty else ""
        else:
            defaults[feature] = float(pd.to_numeric(df_ml[feature], errors="coerce").median())

    line_train_acc = float(model_line.score(X, y_line))
    days_train_mae = float(mean_absolute_error(y_days, model_days.predict(X)))
    with open(MODEL_META_PATH, "w", encoding="utf-8") as meta_file:
        json.dump({"features": FEATURES, "defaults": defaults}, meta_file)

    return {
        "rows": len(df_ml),
        "classes": len(encoders["Line #"].classes_),
        "line_train_acc": line_train_acc,
        "days_train_mae": days_train_mae,
        "model_dir": str(MODEL_DIR),
    }


def _load_artifacts():
    missing = _ensure_ml_dependencies()
    if missing or xgb is None or joblib is None or LabelEncoder is None:
        deps = ", ".join(missing or ["xgboost", "scikit-learn", "joblib"])
        raise RuntimeError(f"ML dependencies are unavailable in this environment (missing/import-failed: {deps}).")

    model_line_path = MODEL_DIR / "ppc_line_model.json"
    model_days_path = MODEL_DIR / "ppc_days_model.json"
    if not model_line_path.exists() or not model_days_path.exists():
        raise FileNotFoundError("Models not found. Train models first.")

    model_line = xgb.XGBClassifier()
    model_line.load_model(str(model_line_path))
    model_days = xgb.XGBRegressor()
    model_days.load_model(str(model_days_path))

    encoders = {}
    for col in CATEGORICAL_COLS:
        enc_path = MODEL_DIR / f"{col}_ppc_encoder.pkl"
        if not enc_path.exists():
            raise FileNotFoundError(f"Encoder missing: {enc_path.name}")
        encoders[col] = joblib.load(enc_path)

    meta = {"features": FEATURES, "defaults": {}}
    if MODEL_META_PATH.exists():
        try:
            with open(MODEL_META_PATH, "r", encoding="utf-8") as meta_file:
                loaded_meta = json.load(meta_file)
            if isinstance(loaded_meta, dict):
                meta.update(loaded_meta)
        except Exception:
            pass

    return model_line, model_days, encoders, meta


def _encode_value(le: Any, value: str, col_name: str, fallback: str | None = None):
    val = str(value).strip()
    if val not in le.classes_:
        if fallback and str(fallback).strip() in le.classes_:
            val = str(fallback).strip()
        elif len(le.classes_) > 0:
            val = str(le.classes_[0]).strip()
        else:
            allowed = ", ".join(le.classes_[:8])
            raise ValueError(f"Unknown {col_name}: '{val}'. Example valid values: {allowed}")
    return le.transform([val])[0]


def _normalize_po(value: str) -> str:
    return str(value or "").strip().upper()


def _parse_any_date(value) -> date | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    # Fast paths for common API date formats.
    # Prefer Python parsing to avoid per-row pandas overhead in large payloads.
    iso = text
    if iso.endswith("Z"):
        iso = iso[:-1]

    try:
        return datetime.fromisoformat(iso).date()
    except Exception:
        pass

    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            continue

    # Fallback for odd formats.
    parsed = pd.to_datetime(pd.Series([text]), errors="coerce", dayfirst=False).iloc[0]
    if pd.isna(parsed):
        return None
    return parsed.date()


def _format_display_date(value) -> str:
    parsed = _parse_any_date(value)
    if parsed is not None:
        return parsed.strftime("%d-%b-%Y")
    return str(value or "").strip()


def _load_live_planner_cache() -> list[dict]:
    if not LIVE_PPC_CACHE_PATH.exists():
        return []

    try:
        with open(LIVE_PPC_CACHE_PATH, "r", encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
    except Exception:
        return []

    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _save_live_planner_cache(rows: list[dict]):
    try:
        LIVE_PPC_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LIVE_PPC_CACHE_PATH, "w", encoding="utf-8") as cache_file:
            json.dump(rows or [], cache_file, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _compute_data_hash(rows: list[dict]) -> str:
    """Quick hash of data for change detection (no API call needed if unchanged)"""
    try:
        data_str = json.dumps([{k: v for k, v in row.items() if k != 'raw'} for row in rows], sort_keys=True, default=str)
        return hash(data_str) % (2 ** 32)
    except Exception:
        return ""


def _is_cache_fresh() -> bool:
    """Check if cached data is still valid"""
    global LIVE_PPC_LAST_FETCH_TIME
    return (time.time() - LIVE_PPC_LAST_FETCH_TIME) < LIVE_PPC_CACHE_TTL


def _fetch_live_planner_background():
    """Background thread function - fetches API data without blocking UI"""
    global LIVE_PPC_LAST_FETCH_TIME, LIVE_PPC_LAST_SYNC_HASH
    try:
        print(f"[BG-FETCH] Starting background API call at {datetime.now().strftime('%H:%M:%S')}", flush=True)
        request = Request(LIVE_PPC_ENDPOINT, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=LIVE_PPC_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        
        new_hash = _compute_data_hash(list(_coerce_live_records(payload)))
        LIVE_PPC_LAST_FETCH_TIME = time.time()
        LIVE_PPC_LAST_SYNC_HASH = new_hash
        
        print(f"[BG-FETCH] ✅ Successful fetch, hash={new_hash}", flush=True)
        LIVE_PPC_BG_FETCH_QUEUE.put({"success": True, "payload": payload, "hash": new_hash})
    except Exception as e:
        print(f"[BG-FETCH] ❌ Failed: {type(e).__name__}. Cache will be used.", flush=True)
        LIVE_PPC_BG_FETCH_QUEUE.put({"success": False, "error": str(e)})


def _get_plan_number(row: dict | pd.Series | None) -> str:
    if row is None:
        return ""

    if isinstance(row, pd.Series):
        row = row.to_dict()

    if not isinstance(row, dict):
        return ""

    for field in PLAN_NUMBER_FIELDS:
        value = row.get(field)
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text and text.lower() not in {"nan", "none"}:
            return text
    return ""


@lru_cache(maxsize=1)
def _load_sewing_plan_df() -> pd.DataFrame:
    if not EXCEL_PATH.exists():
        return pd.DataFrame()

    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name="Sewing Loading Plan", skiprows=2)
    except Exception:
        return pd.DataFrame()

    # Standardize expected columns (keep exact names used in sheet)
    for col in ["PO#", "Cstmr", "Style", "Product", "Old/New", "Fabric", "wash Type", "Color", "SAM", "Plan Qty", "Pln Eff %", "Bal Sew", "Ttl Stch"]:
        if col not in df.columns:
            df[col] = None
    return df


def _lookup_inputs_by_po(po_number: str) -> dict:
    po_key = _normalize_po(po_number)
    if not po_key:
        return {}

    df = _load_sewing_plan_df()
    if df.empty or "PO#" not in df.columns:
        return {}

    series = df["PO#"].astype(str).str.strip().str.upper()
    match_df = df[series == po_key]
    if match_df.empty:
        return {}

    row = match_df.iloc[0]

    product = None
    if not pd.isna(row.get("Product")):
        product = str(row.get("Product")).strip()
    if not product and not pd.isna(row.get("Old/New")):
        product = str(row.get("Old/New")).strip()

    customer = None if pd.isna(row.get("Cstmr")) else str(row.get("Cstmr")).strip().upper()
    style = None if pd.isna(row.get("Style")) else str(row.get("Style")).strip()
    if product:
        product = product.strip().title()

    return {
        "customer": customer,
        "style": style,
        "product": product or None,
        "fabric": None if pd.isna(row.get("Fabric")) else str(row.get("Fabric")).strip().upper(),
        "wash_type": None if pd.isna(row.get("wash Type")) else str(row.get("wash Type")).strip().title(),
        "color": None if pd.isna(row.get("Color")) else str(row.get("Color")).strip().upper(),
        "sam": None if pd.isna(row.get("SAM")) else float(row.get("SAM")),
        "plan_qty": None if pd.isna(row.get("Plan Qty")) else float(row.get("Plan Qty")),
        "pln_eff_num": _normalize_efficiency(row.get("Pln Eff %")),
        "bal_sew": None if pd.isna(row.get("Bal Sew")) else float(row.get("Bal Sew")),
    }


def _get_record_value(record: dict, *aliases, default=None):
    if not isinstance(record, dict):
        return default

    for alias in aliases:
        if alias in record:
            value = record.get(alias)
            if value is None or pd.isna(value):
                continue
            text = str(value).strip()
            if text and text.lower() not in {"nan", "none"}:
                return value
    return default


def _coerce_live_records(payload) -> list[dict]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]

    if isinstance(payload, dict):
        for key in ("items", "data", "records", "result", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]

        if any(key in payload for key in ("PO", "PO#", "BPO", "BPO#", "BPO Number", "PO Number")):
            return [payload]

    return []


def _get_live_sale_order_creation_date(record: dict):
    if not isinstance(record, dict):
        return ""

    def _same_calendar_date(value_a, value_b) -> bool:
        date_a = _parse_any_date(value_a)
        date_b = _parse_any_date(value_b)
        return date_a is not None and date_b is not None and date_a == date_b

    expected_shipment_date = _get_record_value(
        record,
        "expected_shipment_date",
        "expectedShipmentDate",
        default="",
    )

    direct_value = _get_record_value(
        record,
        "sale_order_creation_date",
        "sale_order_cretion_date",
        "saleOrderCreationDate",
        "saleOrderCretionDate",
        "order_confirm_date",
        "sales_order_date",
        "order_date",
        default="",
    )
    if direct_value:
        return direct_value

    created_at_value = _get_record_value(record, "created_at", "createdAt", default="")
    if created_at_value and not _same_calendar_date(created_at_value, expected_shipment_date):
        return created_at_value

    raw_record = record.get("raw")
    if isinstance(raw_record, dict):
        raw_expected_shipment_date = _get_record_value(
            raw_record,
            "expected_shipment_date",
            "expectedShipmentDate",
            default="",
        )
        raw_value = _get_record_value(
            raw_record,
            "sale_order_creation_date",
            "sale_order_cretion_date",
            "saleOrderCreationDate",
            "saleOrderCretionDate",
            "order_confirm_date",
            "sales_order_date",
            "order_date",
            default="",
        )
        if raw_value:
            return raw_value

        raw_created_at = _get_record_value(raw_record, "created_at", "createdAt", default="")
        if raw_created_at and not _same_calendar_date(raw_created_at, raw_expected_shipment_date):
            return raw_created_at

    return ""


def _get_live_record_date_for_filter(record: dict):
    if not isinstance(record, dict):
        return ""

    record_date = _get_record_value(record, "record_date", "recordDate", default="")
    if record_date:
        return record_date

    updated_at = _get_record_value(record, "updated_at", "updatedAt", default="")
    if updated_at:
        return updated_at

    raw_record = record.get("raw")
    if isinstance(raw_record, dict):
        raw_record_date = _get_record_value(raw_record, "record_date", "recordDate", default="")
        if raw_record_date:
            return raw_record_date

        raw_updated_at = _get_record_value(raw_record, "updated_at", "updatedAt", default="")
        if raw_updated_at:
            return raw_updated_at

    return _get_live_sale_order_creation_date(record)


def _is_today_record(record: dict) -> bool:
    """Check if record is from today (STRICT date filtering)"""
    filter_date_text = _get_live_record_date_for_filter(record)

    if not filter_date_text:
        return False

    record_date = _parse_any_date(filter_date_text)
    if record_date is None:
        return False

    today = date.today()
    return record_date == today


def _normalize_live_record(record: dict) -> dict:
    # Direct field access matching actual API response
    po_value = record.get("bpo_number", "")
    po_text = _normalize_po(po_value)

    customer = record.get("customer", "")
    style = record.get("style_number", "")
    product = record.get("product_type", "New")
    fabric = record.get("fabric", "UNKNOWN")
    wash_type = record.get("wash_type", "Unknown")
    color = record.get("color", "UNKNOWN")

    sam_raw = record.get("sam")
    plan_qty_raw = record.get("order_qty")
    eff_raw = record.get("efficiency")
    bal_sew_raw = record.get("balance")

    # Fast numeric conversion
    try:
        sam = float(sam_raw) if sam_raw else None
    except (TypeError, ValueError):
        sam = None
    
    try:
        plan_qty = float(plan_qty_raw) if plan_qty_raw else None
    except (TypeError, ValueError):
        plan_qty = None
    
    try:
        bal_sew = float(bal_sew_raw) if bal_sew_raw else None
    except (TypeError, ValueError):
        bal_sew = None

    priority = record.get("priority", "Normal")
    status = record.get("status", "Live")
    sale_order_creation_date = _get_live_sale_order_creation_date(record)
    expected_shipment_date = record.get("expected_shipment_date", "")
    filter_record_date = _get_live_record_date_for_filter(record)
    record_date = _parse_any_date(filter_record_date)

    return {
        "bpo_number": po_text,
        "po": po_text,
        "customer": str(customer).strip().upper() if customer else "",
        "style": str(style).strip() if style else "",
        "product": str(product).strip().title() if product else "New",
        "fabric": str(fabric).strip().upper() if fabric else "UNKNOWN",
        "wash_type": str(wash_type).strip().title() if wash_type else "Unknown",
        "color": str(color).strip().upper() if color else "UNKNOWN",
        "sam": sam,
        "plan_qty": plan_qty,
        "pln_eff_num": _normalize_efficiency(eff_raw),
        "bal_sew": bal_sew,
        "priority": str(priority).strip() if priority else "Normal",
        "status": str(status).strip() if status else "Live",
        "sale_order_creation_date": str(sale_order_creation_date).strip() if sale_order_creation_date else "",
        "sale_order_cretion_date": str(sale_order_creation_date).strip() if sale_order_creation_date else "",
        "updated_at": str(_get_record_value(record, "updated_at", "updatedAt", default="") or "").strip(),
        "expected_shipment_date": str(expected_shipment_date).strip() if expected_shipment_date else str(_get_record_value(record, "expected_shipment_date", "expectedShipmentDate", default="") or "").strip(),
        "record_date": record_date.isoformat() if record_date else "",
        "raw": record,
    }


def _is_today_cached_row(row: dict) -> bool:
    """Validate cached/normalized row belongs to today's date only."""
    if not isinstance(row, dict):
        return False

    today = date.today()
    candidates = [_get_live_sale_order_creation_date(row), row.get("sale_order_cretion_date"), row.get("record_date")]
    for value in candidates:
        parsed = _parse_any_date(value)
        if parsed is not None and parsed == today:
            return True
    return False


def _fetch_live_planner_records(force_refresh: bool = False) -> list[dict]:
    """Fetch live planner records with intelligent caching and background fetching"""
    global LIVE_PPC_LAST_FETCH_TIME
    
    # ===== INSTANT RESPONSE PHASE: Use cache if available and valid =====
    cached_data = [row for row in _load_live_planner_cache() if _is_today_cached_row(row)]
    if cached_data and _is_cache_fresh() and not force_refresh:
        print(f"[CACHE-HIT] Using fresh cache ({len(cached_data)} records)", flush=True)
        return cached_data  # Return instantly while background fetch happens
    
    # ===== FALLBACK PHASE: Try API with short timeout for fresh data =====
    try:
        print(f"[API-CALL] Fetching from API with {LIVE_PPC_TIMEOUT}s timeout", flush=True)
        request = Request(LIVE_PPC_ENDPOINT, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=LIVE_PPC_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        print(f"[API-SUCCESS] Received {len(str(payload))} bytes", flush=True)
        LIVE_PPC_LAST_FETCH_TIME = time.time()
    except Exception as e:
        print(f"[API-TIMEOUT] {type(e).__name__}: {e}. Using cache.", flush=True)
        return cached_data if cached_data else []

    # ===== PROCESS NEW API DATA =====
    seen = set()
    records = []
    all_records = list(_coerce_live_records(payload))
    
    skipped_no_po = 0
    skipped_duplicate = 0
    skipped_existing = 0
    skipped_old_date = 0  # Track old records filtered out
    duplicate_po_numbers = []
    
    if all_records:
        print(f"[PARSE] Processing {len(all_records)} API records", flush=True)
    
    today = date.today()
    if DEBUG_DATE_FILTER:
        print(f"[DATE-FILTER] Today's date: {today.isoformat()}", flush=True)

    reject_logged = 0
    
    for i, record in enumerate(all_records):
        # ===== DATE FILTER (FIRST CHECK) - Only show today's data =====
        if LIVE_PPC_ONLY_TODAY and not _is_today_record(record):
            skipped_old_date += 1
            if DEBUG_DATE_FILTER and reject_logged < max(0, int(DEBUG_DATE_FILTER_LIMIT)):
                reject_logged += 1
                bpo = record.get("bpo_number", "N/A") if isinstance(record, dict) else "N/A"
                filter_date_text = _get_live_record_date_for_filter(record) if isinstance(record, dict) else ""
                print(f"[DATE-REJECT] BPO: {bpo} | Filter Date: {filter_date_text}", flush=True)
            continue
        
        po_value = record.get("bpo_number", "")
        po_key = _normalize_po(po_value)
        
        if not po_key:
            skipped_no_po += 1
            continue
            
        if po_key in seen:
            skipped_duplicate += 1
            if len(duplicate_po_numbers) < 5:
                duplicate_po_numbers.append(po_key)
            continue
        
        existing_in_plans = any(_normalize_po(_get_plan_number(plan)) == po_key for plan in SAVED_PLANS if isinstance(plan, dict))
        if existing_in_plans:
            skipped_existing += 1
            
        seen.add(po_key)
        normalized = _normalize_live_record(record)
        records.append(normalized)

    print(f"[SUMMARY] {len(records)} new (TODAY ONLY) | {skipped_old_date} old-date | {skipped_duplicate} dupes | {skipped_existing} in-plans | {skipped_no_po} no-BPO", flush=True)
    if duplicate_po_numbers:
        print(f"[DUPLICATE-BPO] {', '.join(duplicate_po_numbers)}", flush=True)
    return records


def _dedupe_saved_plan_rows(rows: list[dict]) -> list[dict]:
    unique_rows = []
    seen_po = set()

    for row in reversed(rows or []):
        po_key = _normalize_po(_get_plan_number(row))
        if not po_key or po_key in seen_po:
            continue
        seen_po.add(po_key)
        unique_rows.append(row)

    return unique_rows


def _upsert_saved_plan_row(plan_row: dict):
    global SAVED_PLANS

    po_key = _normalize_po(_get_plan_number(plan_row))
    if not po_key:
        raise ValueError("Plan is missing BPO Number")

    remaining_rows = [row for row in SAVED_PLANS if _normalize_po(_get_plan_number(row)) != po_key]
    SAVED_PLANS = [plan_row] + remaining_rows


def _find_live_plan_by_po(po_number: str, live_rows: list[dict] | None = None):
    po_key = _normalize_po(po_number)
    if not po_key:
        return None

    for row in live_rows or []:
        if _normalize_po(_get_plan_number(row)) == po_key:
            return row
    return None


def _build_live_planner_table(live_rows: list[dict]) -> html.Div:
    if not live_rows:
        return dbc.Alert("No live BPO Number records found from the endpoint.", color="warning", className="mb-0")

    saved_po_keys = {_normalize_po(_get_plan_number(row)) for row in SAVED_PLANS if isinstance(row, dict)}

    table_rows = []
    for row in live_rows:
        po_key = _normalize_po(_get_plan_number(row))
        duplicate_badge = dbc.Badge("Duplicate", color="danger") if po_key in saved_po_keys else dbc.Badge("New", color="success")
        display_sale_order_creation_date = _format_display_date(_get_live_sale_order_creation_date(row))
        display_ex_mill = _format_display_date(
            row.get("expected_shipment_date")
            or (row.get("raw") or {}).get("expected_shipment_date")
            or ""
        )
        table_rows.append(
            html.Tr([
                html.Td(str(_get_plan_number(row))),
                html.Td(str(row.get("customer", ""))),
                html.Td(str(row.get("style", ""))),
                html.Td(_format_plan_qty(float(row.get("plan_qty", 0) or 0))),
                html.Td(f"{float(row.get('sam', 0) or 0):.2f}" if row.get("sam") is not None else ""),
                html.Td(display_sale_order_creation_date),
                html.Td(display_ex_mill),
                html.Td(duplicate_badge),
            ])
        )

    return dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th("BPO Number"),
                html.Th("Cstmr"),
                html.Th("Style"),
                html.Th("Qty"),
                html.Th("SAM"),
                html.Th("Sale Order Creation Date"),
                html.Th("EX-Mill"),
                html.Th("Plan"),
            ])),
            html.Tbody(table_rows),
        ],
        striped=True,
        bordered=True,
        hover=True,
        responsive=True,
    )


ENCODER_CACHE = {col: [] for col in CATEGORICAL_COLS}
PREDICTION_RESULTS = []
PREDICTION_QUEUE = []
SAVED_PLANS = []


def _load_encoder_cache():
    global ENCODER_CACHE
    if joblib is None:
        return False
    try:
        for col in CATEGORICAL_COLS:
            enc_path = MODEL_DIR / f"{col}_ppc_encoder.pkl"
            if enc_path.exists():
                le = joblib.load(enc_path)
                ENCODER_CACHE[col] = sorted(list(le.classes_))
        return True
    except Exception:
        return False


def _load_saved_plans():
    if not PLAN_HISTORY_PATH.exists():
        return []

    try:
        df = pd.read_csv(PLAN_HISTORY_PATH)
        return _dedupe_saved_plan_rows(df.to_dict("records"))
    except Exception:
        return []


def _persist_saved_plans():
    PLAN_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    clean_rows = _dedupe_saved_plan_rows(SAVED_PLANS)
    SAVED_PLANS[:] = clean_rows
    pd.DataFrame(clean_rows).to_csv(PLAN_HISTORY_PATH, index=False)
    _get_saved_plans_df._last_signature = _plan_history_signature()


def _get_saved_plans_df(month_value=None):
    global SAVED_PLANS
    
    # ===== CACHED READ (Only reload if file modified) =====
    csv_signature = _plan_history_signature()
    
    # Check if we need to reload (file modified, or first load)
    if not hasattr(_get_saved_plans_df, '_last_signature') or _get_saved_plans_df._last_signature != csv_signature:
        if PLAN_HISTORY_PATH.exists():
            try:
                print(f"[CACHE-MISS] Reloading CSV from disk", flush=True)
                latest_df = pd.read_csv(PLAN_HISTORY_PATH)
                SAVED_PLANS = _dedupe_saved_plan_rows(latest_df.to_dict("records"))
                _get_saved_plans_df._last_signature = csv_signature
            except Exception as e:
                print(f"[ERROR] Failed to load CSV: {e}", flush=True)
        else:
            _get_saved_plans_df._last_signature = csv_signature
    else:
        print(f"[CACHE-HIT] Using cached SAVED_PLANS ({len(SAVED_PLANS)} records)", flush=True)

    if not SAVED_PLANS:
        return pd.DataFrame()

    # ===== FAST FILTERING (Avoid repeated pandas operations) =====
    df = pd.DataFrame(SAVED_PLANS)
    
    if "BPO Number" not in df.columns and "PO#" in df.columns:
        df["BPO Number"] = df["PO#"]
    
    if "BPO Number" in df.columns:
        df = df.drop_duplicates(subset=["BPO Number"], keep="first")
    
    if month_value and "Ex-mill Mnth" in df.columns:
        df = df[df["Ex-mill Mnth"] == month_value]
    
    if "Created At" in df.columns:
        df = df.sort_values(by="Created At", ascending=False)
    
    return df
def _get_month_options():
    df = _get_saved_plans_df()
    if df.empty or "Ex-mill Mnth" not in df.columns:
        return []

    month_values = [str(v).strip() for v in df["Ex-mill Mnth"].dropna().tolist() if str(v).strip()]
    seen = set()
    unique_months = []
    for month in month_values:
        if month not in seen:
            seen.add(month)
            unique_months.append(month)
    return [{"label": month, "value": month} for month in unique_months]


_load_encoder_cache()
SAVED_PLANS = _load_saved_plans()

# Initialize cache tracking for _get_saved_plans_df
_get_saved_plans_df._last_signature = (0, 0)  # Track CSV signature for caching
def _add_workdays_sunday_off(start_date: datetime, days: int) -> datetime:
    if days <= 0:
        return start_date

    current = start_date
    remaining = int(days)
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() != 6:  # Sunday off, Mon-Sat working
            remaining -= 1
    return current


def _parse_plan_date(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d-%b-%Y")
    except ValueError:
        return None


def _build_prediction_row(po_number: str, customer: str, style: str, product: str, sam: float, plan_qty: float, pred_line: str, pred_days: int, expected_shipment_date_raw: str | None = None, sale_order_creation_date_raw: str | None = None) -> dict:
    now = datetime.now()
    po_value = str(po_number or "").strip() or f"AUTO-{now.strftime('%y%m%d-%H%M%S')}"
    previous_row = SAVED_PLANS[-1] if SAVED_PLANS else None
    first_row = SAVED_PLANS[0] if SAVED_PLANS else None

    # Add 3% buffer to planned quantity
    plan_qty = float(plan_qty) * 1.03

    start_sew_date = _parse_plan_date(previous_row.get("End Sew Date")) if previous_row else None
    if start_sew_date is None:
        start_sew_date = now + timedelta(days=5)

    base_start_date = _parse_plan_date(first_row.get("Strt Sw Out Dt")) if first_row else None
    if base_start_date is None:
        base_start_date = start_sew_date

    induction_date = start_sew_date - timedelta(days=5)

    # Sewing Loading Plan formulas:
    # O = ((58*480)/M) * N
    # S = Q - R
    # T = S / C   (row-1 dependency ignored for standalone prediction)
    # U = V - 5
    # W = WORKDAY.INTL(V, T, 11) -> Sunday off work calendar
    # Y = AC - W
    line_machines = 58
    working_mins_per_day = 480
    pln_efficiency = 0.75

    ttl_stch = 0.0  # New generated plan starts with zero stitched quantity
    p_dy_cpcty = ((line_machines * working_mins_per_day) / sam) * pln_efficiency if sam > 0 else 0.0
    bal_sew = max(0.0, float(plan_qty) - ttl_stch)
    own_days = (bal_sew / p_dy_cpcty) if p_dy_cpcty > 0 else float(max(1, int(pred_days)))
    prev_com_days = 0.0
    if previous_row:
        try:
            prev_com_days = float(previous_row.get("Com Dys Wk", 0) or 0)
        except Exception:
            prev_com_days = 0.0

    com_dys_wk = round(own_days + prev_com_days, 2)

    end_sew_date = _add_workdays_sunday_off(base_start_date, int(ceil(com_dys_wk)))

    # Business target: EX-MILL should follow API expected shipment date when available.
    target_ex_mill = _parse_any_date(expected_shipment_date_raw)
    if target_ex_mill is not None:
        ex_mill_date = datetime.combine(target_ex_mill, datetime.min.time())
    else:
        ex_mill_date = end_sew_date

    bal_days = (ex_mill_date.date() - end_sew_date.date()).days
    ind_cut_qty = plan_qty
    ex_mill_week = int(ex_mill_date.isocalendar()[1])
    ex_mill_month = ex_mill_date.strftime("%b %y")
    
    return {
        "Created At": now.strftime("%d-%b-%Y %H:%M"),
        "Line #": pred_line,
        "BPO Number": po_value,
        "PO#": po_value,
        "Cstmr": customer,
        "Style": style,
        "Product": product,
        "SAM": round(sam, 2),
        "Pln Eff %": f"{pln_efficiency*100:.1f}%",
        "P.Dy Cpcty": round(p_dy_cpcty, 0),
        "Ind /Cut Qty": int(ind_cut_qty),
        "Plan Qty": int(plan_qty),
        "Ttl Stch": round(ttl_stch, 0),
        "Bal Sew": int(bal_sew),
        "Com Dys Wk": com_dys_wk,
        "Indc Target": induction_date.strftime("%d-%b-%Y"),
        "Strt Sw Out Dt": start_sew_date.strftime("%d-%b-%Y"),
        "End Sew Date": end_sew_date.strftime("%d-%b-%Y"),
        "PPC Status": "Planned",
        "Bal Days": bal_days,
        "EX-MILL": ex_mill_date.strftime("%d-%b-%Y"),
        "expected_shipment_date": ex_mill_date.strftime("%d-%b-%Y"),
        "EX-MILL wk": ex_mill_week,
        "Ex-mill Mnth": ex_mill_month,
        "Line Allocation": pred_line,
        "Old/New": product,
        "LT": pred_days,
        "sale_order_creation_date": str(sale_order_creation_date_raw or "").strip(),
        "Sale Order Creation Date": _format_display_date(sale_order_creation_date_raw),
    }


def _build_prediction_review_card(pending_payload: dict, remaining_count: int = 0):
    pred_row = pending_payload.get("pred_row", {}) if isinstance(pending_payload, dict) else {}
    po_number = str(pending_payload.get("po_number", "")) if isinstance(pending_payload, dict) else ""
    top_line_recos = pending_payload.get("top_line_recos", []) if isinstance(pending_payload, dict) else []

    key_cols = [
        "Line #", "BPO Number", "Sale Order Creation Date", "Cstmr", "Style", "Product", "Plan Qty", "SAM",
        "Pln Eff %", "P.Dy Cpcty", "Ttl Stch", "Bal Sew", "Com Dys Wk",
        "Strt Sw Out Dt", "End Sew Date", "PPC Status"
    ]
    table_rows = [html.Tr([html.Td(str(pred_row.get(col, ""))) for col in key_cols])]

    top3_rows = [
        html.Tr([
            html.Td(str(item.get("rank", ""))),
            html.Td(str(item.get("line", ""))),
            html.Td(f"{float(item.get('score', 0)) * 100:.1f}%"),
        ])
        for item in top_line_recos
    ]

    queue_note = f" {remaining_count} more pending." if remaining_count > 0 else ""
    return dbc.Card([
        dbc.CardBody([
            dbc.Alert(
                f"Auto prediction generated from API for BPO Number {po_number}. Click OK to save, or NO to discard.{queue_note}",
                color="warning",
                className="mb-3"
            ),
            html.H6("Top 3 Recommended Lines", className="mb-2"),
            html.Table([
                html.Thead(html.Tr([html.Th("Rank"), html.Th("Line"), html.Th("Confidence")], style={"background": "#111827", "color": "#00c6ff"})),
                html.Tbody(top3_rows),
            ], style={"width": "100%", "borderCollapse": "collapse", "fontSize": "12px", "marginBottom": "12px"}),
            html.Table([
                html.Thead(html.Tr([html.Th(col, style={"fontSize": "12px"}) for col in key_cols], style={"background": "#111827", "color": "#00c6ff"})),
                html.Tbody(table_rows),
            ], style={"width": "100%", "borderCollapse": "collapse", "fontSize": "12px"}),
            dbc.Row([
                dbc.Col(dbc.Button("OK", id="prediction-approve-btn", color="success", className="w-100"), md=3),
                dbc.Col(dbc.Button("NO", id="prediction-reject-btn", color="danger", className="w-100"), md=3),
            ], className="g-2 mt-3")
        ])
    ], className="kpi-card")


# ================== ORDER TRACKER HELPERS ==================
def build_stage_flow(order: dict) -> html.Div:
    stages = order.get("stages", [])
    if not stages:
        return html.Div("No stages data")
    
    stage_elements = []
    for i, stage in enumerate(stages):
        status = stage.get("status", "pending")
        lead_days = stage.get("lead_days", 0)
        
        if status == "done":
            color = "#00e5a0"
            icon = "✓"
        elif status == "current":
            color = "#00c6ff"
            icon = "●"
        else:
            color = "#64748b"
            icon = "○"
        
        stage_elem = html.Div([
            html.Span(icon, style={"fontSize": "18px", "fontWeight": "700", "color": color}),
            html.Div(stage["name"], style={"fontSize": "11px", "fontWeight": "600", "marginTop": "4px"}),
            html.Div(f"{lead_days}d", style={"fontSize": "9px", "color": "#64748b", "marginTop": "2px"}),
        ], style={"textAlign": "center", "flex": "1"})
        
        stage_elements.append(stage_elem)
        if i < len(stages) - 1:
            arrow = html.Div("→", style={"fontSize": "16px", "color": "#1e2d4a", "padding": "0 8px"})
            stage_elements.append(arrow)
    
    return html.Div(stage_elements, style={
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "center",
        "gap": "8px",
        "padding": "16px",
        "background": "#0a0e1a",
        "borderRadius": "10px",
        "marginBottom": "12px",
        "overflow": "auto"
    })


def _get_current_stage(order: dict) -> dict:
    for stage in order.get("stages", []):
        if stage.get("status") == "current":
            return stage

    for stage in order.get("stages", []):
        if stage.get("status") != "done":
            return stage

    return {}


def build_order_analysis(order: dict) -> dbc.Card:
    stages = order.get("stages", [])
    total_stages = len(stages)
    done_stages = sum(1 for stage in stages if stage.get("status") == "done")
    current_stages = sum(1 for stage in stages if stage.get("status") == "current")
    pending_stages = sum(1 for stage in stages if stage.get("status") == "pending")

    progress_pct = round((done_stages / total_stages) * 100, 1) if total_stages else 0
    total_lead = sum(int(stage.get("lead_days", 0)) for stage in stages)
    done_lead = sum(int(stage.get("lead_days", 0)) for stage in stages if stage.get("status") == "done")
    remaining_lead = max(0, total_lead - done_lead)
    current_stage = _get_current_stage(order)

    if remaining_lead >= 8:
        risk_text = "High"
        risk_color = "danger"
    elif remaining_lead >= 4:
        risk_text = "Medium"
        risk_color = "warning"
    else:
        risk_text = "Low"
        risk_color = "success"

        return dbc.Card([
        dbc.CardBody([
            html.Div("Order Analysis", className="section-title mb-3"),
            dbc.Row([
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.Div("Progress", className="text-muted small"),
                    html.Div(f"{progress_pct}%", className="kpi-value text-info", style={"fontSize": "24px"}),
                ]), className="kpi-card"), md=3),
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.Div("Stage Split", className="text-muted small"),
                    html.Div(f"D:{done_stages} | C:{current_stages} | P:{pending_stages}", className="text-light", style={"fontWeight": "700"}),
                ]), className="kpi-card"), md=3),
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.Div("Remaining Lead Time", className="text-muted small"),
                    html.Div(f"{remaining_lead} days", className="text-success", style={"fontWeight": "700", "fontSize": "20px"}),
                ]), className="kpi-card"), md=3),
                dbc.Col(dbc.Card(dbc.CardBody([
                    html.Div("Delay Risk", className="text-muted small"),
                    dbc.Badge(risk_text, color=risk_color, className="mt-2"),
                ]), className="kpi-card"), md=3),
            ], className="g-2"),
            html.Div([
                html.Div(f"Current Stage: {current_stage.get('name', 'N/A')}", style={"fontWeight": "700"}),
                html.Div(f"Order: {order.get('bpo', order.get('po', ''))} | Customer: {order.get('customer', '')} | Line: {order.get('line', '')}", className="text-muted small"),
            ], style={"marginTop": "12px"}),
        ])
    ], className="kpi-card")


def build_order_tracker(filtered_orders=None) -> html.Div:
    orders_to_show = filtered_orders if filtered_orders is not None else orders
    order_cards = []

    if not orders_to_show:
        return html.Div(dbc.Alert("No matching order found.", color="warning"))

    for order in orders_to_show:
        current_stage = _get_current_stage(order)
        order_bpo = str(order.get("bpo", order.get("po", "")))
        
        status_color = "success" if order.get("ppcStatus") == "Completed" else "info"
        
        card = dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.Div([
                        html.Div(f"BPO Number: {order_bpo}", style={"fontWeight": "700", "color": "#00c6ff", "fontSize": "14px"}),
                        html.Div(f"Customer: {order['customer']} | Line: {order['line']}", style={"fontSize": "12px", "color": "#64748b", "marginTop": "4px"}),
                    ]),
                    html.Div([
                        dbc.Badge(order.get("ppcStatus", "Pending"), color=status_color, className="ms-2")
                    ], style={"textAlign": "right"})
                ], style={"display": "flex", "justifyContent": "space-between", "marginBottom": "12px"}),
                
                html.Div([
                    html.Div(f"📍 Current Stage: {current_stage['name'] if current_stage else 'N/A'}", style={"fontWeight": "600", "color": "#00c6ff", "marginBottom": "8px", "fontSize": "12px"}),
                    html.Div(f"⏱️ Lead Time: {current_stage.get('lead_days', 0)} days", style={"fontSize": "11px", "color": "#00e5a0"}),
                ], style={"padding": "8px", "background": "#111827", "borderRadius": "6px", "marginBottom": "12px"}),
                
                build_stage_flow(order),
            ])
        ], className="kpi-card", style={"marginBottom": "12px"})
        
        order_cards.append(card)
    
    return html.Div(order_cards)


def _saved_plans_as_orders() -> list[dict]:
    df = _get_saved_plans_df()
    if df.empty:
        return []

    for col in ["BPO Number", "PO#", "Cstmr", "Line #", "Style", "PPC Status", "EX-MILL", "Indc Target", "Plan Qty", "SAM", "Created At"]:
        if col not in df.columns:
            df[col] = ""

    # Prefer latest entry per BPO Number (so search shows the most recent plan info)
    if "Created At" in df.columns:
        df = df.sort_values(by="Created At", ascending=False)

    seen_po = set()
    out = []
    for _, row in df.iterrows():
        bpo = str(_get_plan_number(row) or "").strip()
        if not bpo:
            continue
        po_key = bpo.upper()
        if po_key in seen_po:
            continue
        seen_po.add(po_key)

        out.append({
            "bpo": bpo,
            "po": bpo,
            "customer": str(row.get("Cstmr", "") or "").strip(),
            "line": str(row.get("Line #", "") or "").strip(),
            "style": str(row.get("Style", "") or "").strip(),
            "ppcStatus": str(row.get("PPC Status", "") or "Planned").strip() or "Planned",
            "indTarget": str(row.get("Indc Target", "") or "").strip(),
            "exMill": str(row.get("EX-MILL", "") or "").strip(),
            "planQty": row.get("Plan Qty", ""),
            "sam": row.get("SAM", ""),
            # No stage flow available for saved plans; keep empty.
            "stages": [],
        })

    return out


# ================== APP ==================
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
    title="MG PPC Dashboard",
    update_title=None,
)

# Guard against oversized request bodies that can exhaust memory in dev server mode.
app.server.config["MAX_CONTENT_LENGTH"] = int(os.getenv("PPC_MAX_CONTENT_LENGTH", 1 * 1024 * 1024))

app.index_string = '''
<!DOCTYPE html>
<html>
<head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <style>
        :root {
            --bg: #0a0e1a;
            --sidebar: #0d1224;
            --card: #111827;
            --card2: #161f35;
            --accent: #00c6ff;
            --accent2: #0072ff;
            --green: #00e5a0;
            --yellow: #ffc107;
            --red: #00e5a0;
            --text: #e2e8f0;
            --muted: #64748b;
            --border: #1e2d4a;
        }
        body { background: var(--bg); color: var(--text); font-family: 'DM Sans', system-ui, sans-serif; }
        .brand { font-family: 'Rajdhani', sans-serif; font-size: 26px; font-weight: 700; background: linear-gradient(90deg, #00c6ff, #0072ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .nav-item { padding: 12px 14px; border-radius: 10px; cursor: pointer; color: var(--muted); }
        .nav-item.active, .nav-item:hover { background: rgba(0,198,255,0.15); color: var(--accent); }
        .kpi-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 20px; position: relative; }
        .kpi-value { font-family: 'Rajdhani', sans-serif; font-size: 32px; font-weight: 700; }
        .section-title { font-family: 'Rajdhani', sans-serif; font-size: 18px; font-weight: 600; }
        .line-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
        .resource-card { background: linear-gradient(180deg, rgba(17,24,39,0.98), rgba(13,18,36,0.98)); border: 1px solid var(--border); border-radius: 16px; padding: 18px; }
        .resource-chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; background: rgba(0,198,255,0.10); color: var(--accent); font-size: 12px; font-weight: 600; border: 1px solid rgba(0,198,255,0.22); }
        .resource-chip-muted { background: rgba(148,163,184,0.10); color: #cbd5e1; border-color: rgba(148,163,184,0.18); }
        .resource-table-wrap { overflow-x: auto; border: 1px solid rgba(30,45,74,0.9); border-radius: 14px; }
        .resource-table-wrap table { margin-bottom: 0; }
        .resource-table-wrap thead th { background: #0b1220; color: #00c6ff; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; white-space: nowrap; }
        .resource-table-wrap tbody td { white-space: nowrap; }
        .eff-high { background: rgba(0,229,160,0.15); color: var(--green); }
        .eff-mid { background: rgba(255,193,7,0.15); color: var(--yellow); }
        .stage-dot { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
        .modal-content { background: var(--card); border: 1px solid var(--border); border-radius: 18px; }

        /* Ensure dcc.Dropdown selected values are visible in dark theme */
        .Select-control {
            background-color: var(--card) !important;
            border-color: var(--border) !important;
            color: var(--text) !important;
        }
        .Select-placeholder,
        .Select--single > .Select-control .Select-value {
            color: var(--muted) !important;
        }
        .Select.has-value.Select--single > .Select-control .Select-value,
        .Select.has-value.is-pseudo-focused.Select--single > .Select-control .Select-value {
            color: var(--text) !important;
        }
        .Select-value-label {
            color: var(--text) !important;
            font-weight: 600;
        }
        .Select.has-value.Select--single > .Select-control .Select-value .Select-value-label,
        .Select.has-value.is-pseudo-focused.Select--single > .Select-control .Select-value .Select-value-label {
            color: var(--text) !important;
            opacity: 1 !important;
        }
        .Select-input > input {
            color: var(--text) !important;
        }
        .Select-menu-outer {
            background-color: var(--sidebar) !important;
            border-color: var(--border) !important;
            color: var(--text) !important;
        }
        .Select-option {
            background-color: var(--sidebar) !important;
            color: var(--text) !important;
        }
        .Select-option.is-focused {
            background-color: var(--card2) !important;
        }
        .Select-option.is-selected {
            background-color: rgba(0,198,255,0.15) !important;
            color: var(--accent) !important;
        }
    </style>
</head>
<body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>
'''

sidebar = html.Div([
    html.Div([
        html.Div("MG PPC", className="brand"),
        html.Div("Production Control", style={"fontSize": "11px", "color": "#64748b", "textTransform": "uppercase"})
    ], style={"padding": "28px 20px 20px", "borderBottom": "1px solid #1e2d4a"}),

    html.Div([
        html.Div([html.Span("📊", style={"marginRight": "12px"}), "Dashboard"], id="nav-dashboard", className="nav-item active", n_clicks=0),
        html.Div([html.Span("📋", style={"marginRight": "12px"}), "PPC +IE"], id="nav-ppc", className="nav-item", n_clicks=0),
        html.Div([html.Span("🧭", style={"marginRight": "12px"}), "Order Tracker"], id="nav-order-tracker", className="nav-item", n_clicks=0),
    ], style={"padding": "24px 12px", "display": "flex", "flexDirection": "column", "gap": "6px"}),

    html.Div([
        html.Div("Sewing Loading Plan<br>Apr 2026 · Active"),
    ], style={"padding": "16px 20px", "borderTop": "1px solid #1e2d4a", "fontSize": "11px", "color": "#64748b"}),

    html.Div(
        "powered by DSBA",
        style={"marginTop": "auto", "padding": "12px 20px", "fontSize": "11px", "color": "#f9c6c6", "textAlign": "center"},
    ),
], style={"width": "220px", "background": "#0d1224", "position": "fixed", "height": "100vh", "borderRight": "1px solid #1e2d4a", "display": "flex", "flexDirection": "column"})


def _page_style(display: str) -> dict:
    return {"padding": "28px", "display": display}


def kpi_card(label, value, sub, color_class, icon, value_id=None):
    return dbc.Card([
        html.Div(icon, style={"position": "absolute", "right": "16px", "top": "16px", "fontSize": "28px", "opacity": "0.15"}),
        html.Div(label, className="text-muted text-uppercase small"),
        html.Div(value, id=value_id, className=f"kpi-value {color_class}"),
        html.Div(sub, className="text-muted small"),
    ], className="kpi-card", style={"height": "100%"})


kpi_row = dbc.Row([
    dbc.Col(kpi_card("Active Lines", "0", "Production lines running", "text-info", "🏭", "kpi-active-lines"), width=3),
    dbc.Col(kpi_card("Active Orders", "0", "Orders in pipeline", "text-success", "📦", "kpi-active-orders"), width=3),
    dbc.Col(kpi_card("Avg Efficiency", "0%", "Target: 75%", "text-warning", "⚡", "kpi-avg-eff"), width=3),
    dbc.Col(kpi_card("Total Plan Qty", "0", "Units this month", "text-primary", "⏰", "kpi-total-plan-qty"), width=3),
], className="mb-4")


def _format_plan_qty(value: float) -> str:
    if value >= 100000:
        return f"{value / 100000:.1f}L"
    if value >= 1000:
        return f"{value / 1000:.1f}K"
    return f"{int(round(value))}"


def _parse_exmill_month(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%b %y")
    except Exception:
        return None


@lru_cache(maxsize=None)
def _load_official_holiday_dates(year: int | None = None) -> set[date]:
    if country_holidays is not None:
        try:
            years = [year] if year is not None else [datetime.now().year]
            holiday_calendar = country_holidays.country_holidays("PK", years=years)
            holiday_dates = {dt for dt in holiday_calendar.keys() if year is None or dt.year == year}
            if holiday_dates:
                return holiday_dates
        except Exception:
            pass

    if not OFFICIAL_HOLIDAYS_PATH.exists():
        return set()

    try:
        df = pd.read_csv(OFFICIAL_HOLIDAYS_PATH)
    except Exception:
        return set()

    if "date" not in df.columns:
        return set()

    if "status" not in df.columns:
        df["status"] = "official"

    status_series = df["status"].astype(str).str.strip().str.lower()
    official_df = df[status_series == "official"].copy()
    official_df["date"] = pd.to_datetime(official_df["date"], errors="coerce").dt.date
    official_df = official_df[official_df["date"].notna()]
    holiday_dates = set(official_df["date"].tolist())
    if year is not None:
        holiday_dates = {dt for dt in holiday_dates if dt.year == year}
    return holiday_dates


def _pakistan_public_holidays_in_month(year: int, month: int) -> tuple[int, int]:
    holiday_dates = {
        dt for dt in _load_official_holiday_dates(year)
        if dt.year == year and dt.month == month
    }
    total_public_holidays = len(holiday_dates)
    non_sunday_public_holidays = sum(1 for dt in holiday_dates if dt.weekday() != 6)
    return total_public_holidays, non_sunday_public_holidays


def _month_workday_stats(month_value: str | None) -> dict:
    base = _parse_exmill_month(month_value) or datetime.now()
    year = int(base.year)
    month = int(base.month)

    month_days = calendar.monthrange(year, month)[1]

    sundays = 0
    for day in range(1, month_days + 1):
        if datetime(year, month, day).weekday() == 6:
            sundays += 1

    # Lay off remains manual/static for now.
    # Holiday is now based on Pakistan public holidays for the selected month.
    lay_off = 0
    holiday, non_sunday_holiday = _pakistan_public_holidays_in_month(year, month)
    work_days = max(0, month_days - sundays - non_sunday_holiday - lay_off)

    return {
        "month_days": month_days,
        "sundays": sundays,
        "holiday": holiday,
        "lay_off": lay_off,
        "work_days": work_days,
    }


def _row_key_from_plan_row(plan_row: dict) -> str:
    created_at = str(plan_row.get("Created At", "") or "").strip()
    bpo_value = str(_get_plan_number(plan_row) or "").strip()
    return f"{created_at}|{bpo_value}"


@lru_cache(maxsize=128)
def _build_line_details_content(selected_line: str, csv_signature: tuple[int, int]):
    plans_df = _get_saved_plans_df()
    if plans_df.empty or "Line #" not in plans_df.columns:
        return f"Line Details - {selected_line}", "", dbc.Alert("No saved plan data available.", color="warning")

    if not selected_line:
        line_series = plans_df["Line #"].astype(str).str.strip()
        non_empty_lines = [line for line in line_series.tolist() if line]
        selected_line = non_empty_lines[0] if non_empty_lines else ""

    if not selected_line:
        return "Line Details", "", dbc.Alert("Select a line from All Month Plans.", color="info")

    line_df = plans_df[plans_df["Line #"].astype(str) == str(selected_line)].copy()
    if line_df.empty:
        return f"Line Details - {selected_line}", "", dbc.Alert(f"No plans found for line {selected_line}.", color="warning")

    if "Created At" in line_df.columns:
        line_df = line_df.sort_values(by="Created At", ascending=False)

    # Stable row key used by Edit buttons.
    if "Created At" not in line_df.columns:
        line_df["Created At"] = ""
    if "BPO Number" not in line_df.columns and "PO#" in line_df.columns:
        line_df["BPO Number"] = line_df["PO#"]
    if "BPO Number" not in line_df.columns:
        line_df["BPO Number"] = ""
    line_df["_row_key"] = line_df.apply(lambda r: _row_key_from_plan_row(r.to_dict()), axis=1)

    # Per day capacity formula: ((58 * 480) / SAM) * plan efficiency
    if "SAM" in line_df.columns and "Pln Eff %" in line_df.columns:
        sam_series = pd.to_numeric(line_df["SAM"], errors="coerce")
        eff_raw = line_df["Pln Eff %"].astype(str).str.replace("%", "", regex=False).str.strip()
        eff_numeric = pd.to_numeric(eff_raw, errors="coerce")
        eff_factor = eff_numeric.where(eff_numeric <= 1.5, eff_numeric / 100.0)
        line_df["Per day capacity"] = (((58.0 * 480.0) / sam_series) * eff_factor).where(sam_series > 0, 0).fillna(0).round(0).astype(int)
    else:
        line_df["Per day capacity"] = 0

    # INDC Target formula: Strt Sw Out Dt - 5 days
    if "Strt Sw Out Dt" in line_df.columns:
        start_dates = pd.to_datetime(line_df["Strt Sw Out Dt"], format="%d-%b-%Y", errors="coerce")
        if start_dates.isna().all():
            start_dates = pd.to_datetime(line_df["Strt Sw Out Dt"], errors="coerce", dayfirst=True)
        line_df["INDC Target"] = (start_dates - pd.to_timedelta(5, unit="D")).dt.strftime("%d-%b-%Y").fillna("")
    else:
        line_df["INDC Target"] = ""

    # EX-Mill display column: expected_shipment_date first, then EX-MILL, then exMill fallback.
    line_df["EX-Mill"] = ""
    if "expected_shipment_date" in line_df.columns:
        line_df["EX-Mill"] = line_df["expected_shipment_date"].fillna("").astype(str).str.strip()
    if "EX-MILL" in line_df.columns:
        fallback_exmill = line_df["EX-MILL"].fillna("").astype(str).str.strip()
        primary_exmill = line_df["EX-Mill"].fillna("").astype(str).str.strip()
        line_df["EX-Mill"] = primary_exmill.where(primary_exmill != "", fallback_exmill)
    if "exMill" in line_df.columns:
        fallback_exmill_camel = line_df["exMill"].fillna("").astype(str).str.strip()
        primary_exmill = line_df["EX-Mill"].fillna("").astype(str).str.strip()
        line_df["EX-Mill"] = primary_exmill.where(primary_exmill != "", fallback_exmill_camel)

    detail_columns = [
        ("BPO Number", "BPO Number"),
        ("Sale Order Creation Date", "Sale Order Creation Date"),
        ("Cstmr", "Customer"),
        ("Style", "Style"),
        ("Plan Qty", "Plan Qty"),
        ("SAM", "SAM"),
        ("Pln Eff %", "Plan Eff %"),
        ("Per day capacity", "Per Day Capacity"),
        ("INDC Target", "INDC Target"),
        ("Strt Sw Out Dt", "Start Sew Out Date"),
        ("End Sew Date", "End Sew Date"),
        ("EX-Mill", "EX-Mill"),
        ("Created At", "Created At"),
    ]

    def _format_line_value(source_col, raw_value):
        if source_col == "SAM":
            sam_num = pd.to_numeric(pd.Series([raw_value]), errors="coerce").iloc[0]
            return f"{float(sam_num):.1f}" if pd.notna(sam_num) else str(raw_value)

        if source_col in {"Plan Qty", "Per day capacity"}:
            num = pd.to_numeric(pd.Series([raw_value]), errors="coerce").iloc[0]
            return str(int(round(float(num)))) if pd.notna(num) else str(raw_value)

        if source_col == "Pln Eff %":
            text = str(raw_value or "").strip().replace("%", "")
            num = pd.to_numeric(pd.Series([text]), errors="coerce").iloc[0]
            if pd.isna(num):
                return str(raw_value)
            eff_pct = float(num) * 100.0 if float(num) <= 1.5 else float(num)
            return f"{int(round(eff_pct))}%"

        return str(raw_value)

    rows = []
    for _, row in line_df.iterrows():
        row_key = str(row.get("_row_key", "")).strip()
        edit_btn = dbc.Button(
            "Edit",
            id={"type": "edit-bpo-btn", "row_key": row_key},
            color="primary",
            size="sm",
        )
        rows.append(
            html.Tr(
                [
                    *[html.Td(_format_line_value(source_col, row.get(source_col, ""))) for source_col, _ in detail_columns],
                    html.Td(edit_btn),
                ]
            )
        )

    details_table = dbc.Table([
        html.Thead(html.Tr([*([html.Th(display_label) for _, display_label in detail_columns]), html.Th("Action")])) ,
        html.Tbody(rows),
    ], bordered=True, striped=True, hover=True, responsive=True)

    active_resources_df, reserve_resources_df, resource_stats = _get_line_active_resources(selected_line, capacity=58)
    if active_resources_df.empty:
        resources_panel = dbc.Alert(f"No skill-matrix resource mapping found for line {selected_line}.", color="secondary", className="mb-0")
    else:
        resource_rows = []
        for _, resource_row in active_resources_df.iterrows():
            resource_rows.append(
                html.Tr([
                    html.Td(str(resource_row.get("resource_name", ""))),
                    html.Td(str(resource_row.get("resource_code", ""))),
                    html.Td(str(resource_row.get("line_name", ""))),
                    html.Td(f"{float(resource_row.get('efficiency_score', 0) or 0):.1f}%"),
                    html.Td(f"{float(resource_row.get('skill_level_score', 0) or 0):.1f}%"),
                    html.Td(str(resource_row.get("availability_state", ""))),
                ])
            )

        resources_table = dbc.Table([
            html.Thead(html.Tr([
                html.Th("Resource"),
                html.Th("Code"),
                html.Th("Line"),
                html.Th("Efficiency"),
                html.Th("Skill"),
                html.Th("Status"),
            ])),
            html.Tbody(resource_rows),
        ], bordered=True, striped=True, hover=True, responsive=True)

        resources_panel = html.Div([
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div("Resources On This Line", className="text-muted small"),
                    html.Div(f"{resource_stats['active_count']}", className="kpi-value text-info", style={"fontSize": "24px"}),
                ], className="resource-chip-muted"), md=12),
            ], className="g-2 mb-3"),
            html.Div(resources_table, className="resource-table-wrap"),
        ], className="resource-card")

    summary = dbc.Alert([
        html.Div(f"{len(line_df)} order(s) running on {selected_line}.", className="mb-1"),
        html.Div(
            f"Resources on this line: {resource_stats.get('active_count', 0)}",
            className="small text-muted",
        ),
    ], color="info", className="mb-0")

    return f"Line Details - {selected_line}", summary, html.Div([
        details_table,
        html.Hr(className="my-3"),
        html.H5("Resources Working on This Line (Active 58)", className="section-title mb-2"),
        resources_panel,
    ])


app.layout = html.Div([
    sidebar,
    html.Div([
        html.Div(id="page-dashboard", children=[
            html.Div([
                html.H1("📊 Production Dashboard", style={"fontFamily": "Rajdhani", "fontSize": "28px", "fontWeight": "700"}),
                html.Span([html.Span(className="live-dot", style={"background": "#00e5a0", "animation": "pulse 1.5s infinite"}), "Live · Apr 2026"],
                          className="badge", style={"background": "rgba(0,198,255,0.1)", "border": "1px solid rgba(0,198,255,0.3)", "color": "#00c6ff", "padding": "4px 12px", "borderRadius": "20px"})
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "28px"}),

            kpi_row,

            html.H4("Active Production Lines", className="section-title mb-3"),

            html.H4("All Month Plans", className="section-title mt-4 mb-3"),
            dbc.Row([
                dbc.Col(dcc.Dropdown(id="ppc-month-filter", placeholder="Filter by Ex-mill month", options=_get_month_options(), clearable=True), md=4),
                dbc.Col(dbc.Input(id="ppc-bpo-search", placeholder="Search by BPO Number", type="text", debounce=True), md=4),
                dbc.Col(
                    html.Div(
                        dbc.Button("Export", id="ppc-download-excel-btn", color="primary", size="sm", className="px-3"),
                        style={"display": "flex", "justifyContent": "flex-end"}
                    ),
                    md=4
                ),
            ], className="g-2 mb-3"),
            dbc.Alert("", id="ppc-download-status", color="secondary", is_open=False, className="mb-2"),
            html.Div(id="ppc-month-filter-status", className="mb-2"),
            html.Div(id="ppc-filtered-table-container", children=dbc.Table.from_dataframe(ppc_data, striped=True, bordered=True, hover=True, id="ppc-table")),
            dbc.Modal([
                dbc.ModalHeader(dbc.ModalTitle("Plan Details", id="bpo-details-modal-title")),
                dbc.ModalBody(id="bpo-details-modal-body"),
                dbc.ModalFooter(dbc.Button("Close", id="bpo-details-close", color="secondary")),
            ], id="bpo-details-modal", is_open=False, size="lg"),
            dcc.Download(id="ppc-download-excel"),

        ], style=_page_style("block")),

        html.Div(id="page-order-tracker", style=_page_style("none"), children=[
            html.H1("🧭 Order Tracker"),
            html.H4("Order Status Tracker", className="section-title mt-4 mb-3"),
            dbc.Row([
                dbc.Col(dbc.Input(id="order-search-input", placeholder="Search by BPO Number, customer, style, or line", type="text", debounce=True), md=8),
                dbc.Col(html.Div(id="order-search-meta"), md=4),
            ], className="g-2 mb-3"),
            html.Div(id="order-tracker-container", children=html.Div()),
            html.Div(id="order-analysis-container", className="mt-3", children=html.Div()),
        ]),

        html.Div(id="page-ppc", style=_page_style("none"), children=[
            html.H1("📋 PPC Planner"),
            html.H4("Live BPO Number Planner", className="section-title mt-4 mb-3"),
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Alert("Waiting for live BPO Number feed...", id="live-planner-status", color="secondary", className="mb-0"),
                            dbc.Alert("AI model waiting for today's live API data...", id="ai-predict-output", color="secondary", className="mb-0 mt-2"),
                            dbc.Alert("Model not trained in this session.", id="ai-train-status", color="secondary", className="mb-0 mt-2"),
                        ], md=9),
                        dbc.Col([
                            dbc.Button("Train AI Models", id="ai-train-btn", color="info", className="w-100"),
                        ], md=3),
                    ], className="g-2 mb-3"),
                    dcc.Loading(
                        id="live-planner-loading",
                        type="default",
                        children=[
                            html.Div(id="live-planner-table", children=dbc.Alert("Live feed will appear here.", color="secondary")),
                        ]
                    ),
                ])
            ], className="kpi-card mb-3"),
            html.H4("Predicted Plan Results", className="section-title mt-4 mb-3"),
            html.Div(id="prediction-results-container", children=[
                dbc.Alert("No predictions yet. Live API data will auto-generate predictions for approval.", color="secondary")
            ]),
            dcc.Interval(id="live-planner-refresh", interval=LIVE_PPC_REFRESH_MS, n_intervals=0, disabled=True),
            dcc.Store(id="live-planner-store", data=[]),
        ]),

        html.Div(id="page-line-details", style=_page_style("none"), children=[
            dbc.Button("<- Back to Dashboard", id="back-to-dashboard", color="secondary", size="sm", className="mb-3"),
            html.H1(id="line-details-title", children="Line Details"),
            html.Div(id="line-details-summary", className="mb-3"),
            html.Div(id="line-details-container", children=dbc.Alert("Select a line from All Month Plans.", color="info")),
        ]),

        dcc.Store(id="selected-line-store", data=None),
        dcc.Store(id="pending-prediction-store", data=None),
        dcc.Store(id="prediction-approval-click-state", data={"ok": 0, "no": 0}),
        dcc.Store(id="saved-plans-refresh", data=0),
        dcc.Store(id="edit-plan-row-key", data=None),

        dbc.Modal([
            dbc.ModalHeader(dbc.ModalTitle("Edit BPO Number Plan")),
            dbc.ModalBody([
                dbc.Alert("", id="edit-plan-alert", color="secondary", is_open=False, className="mb-3"),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Created At"),
                        dbc.Input(id="edit-created-at", type="text", disabled=True),
                    ], md=6),
                    dbc.Col([
                        dbc.Label("BPO Number"),
                        dbc.Input(id="edit-bpo", type="text"),
                    ], md=6),
                ], className="g-2 mb-2"),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Line #"),
                        dbc.Input(id="edit-line", type="text"),
                    ], md=4),
                    dbc.Col([
                        dbc.Label("Cstmr"),
                        dbc.Input(id="edit-customer", type="text"),
                    ], md=4),
                    dbc.Col([
                        dbc.Label("Style"),
                        dbc.Input(id="edit-style", type="text"),
                    ], md=4),
                ], className="g-2 mb-2"),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Product"),
                        dbc.Input(id="edit-product", type="text"),
                    ], md=4),
                    dbc.Col([
                        dbc.Label("SAM"),
                        dbc.Input(id="edit-sam", type="number"),
                    ], md=4),
                    dbc.Col([
                        dbc.Label("Plan Qty"),
                        dbc.Input(id="edit-plan-qty", type="number"),
                    ], md=4),
                ], className="g-2 mb-2"),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Pln Eff %"),
                        dbc.Input(id="edit-eff", type="text", placeholder="e.g. 75%"),
                    ], md=4),
                    dbc.Col([
                        dbc.Label("PPC Status"),
                        dbc.Input(id="edit-status", type="text"),
                    ], md=4),
                    dbc.Col([
                        dbc.Label("EX-MILL"),
                        dbc.Input(id="edit-exmill", type="text", placeholder="e.g. 03-Apr-2026"),
                    ], md=4),
                ], className="g-2 mb-2"),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("Strt Sw Out Dt"),
                        dbc.Input(id="edit-start", type="text", placeholder="e.g. 27-Mar-2026"),
                    ], md=6),
                    dbc.Col([
                        dbc.Label("End Sew Date"),
                        dbc.Input(id="edit-end", type="text", placeholder="e.g. 03-Apr-2026"),
                    ], md=6),
                ], className="g-2"),
            ]),
            dbc.ModalFooter([
                dbc.Button("Save", id="edit-plan-save", color="success"),
                dbc.Button("Cancel", id="edit-plan-cancel", color="secondary", className="ms-2"),
            ]),
        ], id="edit-plan-modal", is_open=False, size="lg"),

    ], style={"marginLeft": "220px"})
])


@callback(
    [
        Output("page-dashboard", "style"),
        Output("page-order-tracker", "style"),
        Output("page-ppc", "style"),
        Output("page-line-details", "style"),
        Output("nav-dashboard", "className"),
        Output("nav-order-tracker", "className"),
        Output("nav-ppc", "className"),
        Output("live-planner-refresh", "disabled"),
    ],
    [
        Input("nav-dashboard", "n_clicks"),
        Input("nav-order-tracker", "n_clicks"),
        Input("nav-ppc", "n_clicks"),
        Input("selected-line-store", "data"),
        Input("back-to-dashboard", "n_clicks"),
    ]
)
def switch_page(_, __, ___, selected_line, ____):
    ctx = dash.callback_context
    if not ctx.triggered:
        return _page_style("block"), _page_style("none"), _page_style("none"), _page_style("none"), "nav-item active", "nav-item", "nav-item", True

    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    if trigger == "back-to-dashboard":
        return _page_style("block"), _page_style("none"), _page_style("none"), _page_style("none"), "nav-item active", "nav-item", "nav-item", True
    if trigger == "selected-line-store" and selected_line:
        # Line details is a drill-down from Dashboard, keep Dashboard highlighted in sidebar.
        return _page_style("none"), _page_style("none"), _page_style("none"), _page_style("block"), "nav-item active", "nav-item", "nav-item", True
    if trigger == "selected-line-store" and not selected_line:
        # Keep the current page unchanged when the store is cleared or re-written as None
        # (e.g. table re-render). This prevents unwanted navigation.
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update
    if trigger == "nav-dashboard":
        return _page_style("block"), _page_style("none"), _page_style("none"), _page_style("none"), "nav-item active", "nav-item", "nav-item", True
    elif trigger == "nav-order-tracker":
        return _page_style("none"), _page_style("block"), _page_style("none"), _page_style("none"), "nav-item", "nav-item active", "nav-item", True
    elif trigger == "nav-ppc":
        return _page_style("none"), _page_style("none"), _page_style("block"), _page_style("none"), "nav-item", "nav-item", "nav-item active", False
    return _page_style("block"), _page_style("none"), _page_style("none"), _page_style("none"), "nav-item active", "nav-item", "nav-item", True


@callback(
    [
        Output("kpi-active-lines", "children"),
        Output("kpi-active-orders", "children"),
        Output("kpi-avg-eff", "children"),
        Output("kpi-total-plan-qty", "children"),
    ],
    [Input("ppc-month-filter", "value"), Input("saved-plans-refresh", "data")],
)
def update_dashboard_kpis(month_value, __):
    df = _get_saved_plans_df(month_value)
    if df.empty and month_value:
        df = _get_saved_plans_df()
    if df.empty:
        return "0", "0", "0%", "0"

    bpo_series = df["BPO Number"] if "BPO Number" in df.columns else df.get("PO#", pd.Series([""] * len(df), index=df.index))

    # ===== OPTIMIZED: Ensure columns exist only once =====
    df = df.assign(
        **{
            "Line #": df.get("Line #", "").astype(str).str.strip(),
            "BPO Number": bpo_series,
            "Pln Eff %": df.get("Pln Eff %", ""),
            "Plan Qty": pd.to_numeric(df.get("Plan Qty", 0), errors="coerce").fillna(0),
        }
    )

    # ===== CALCULATE ALL KPIs IN ONE PASS =====
    print(f"[KPI-CALC] Computing dashboard metrics for {len(df)} records", flush=True)
    
    active_lines = int(df["Line #"].astype(str).str.strip()[df["Line #"].astype(str).str.strip() != ""].nunique())
    active_orders = int((df["BPO Number"].astype(str).str.strip() != "").sum())

    # Efficiency: handle both % and decimal formats
    eff_series = df["Pln Eff %"].astype(str).str.replace("%", "", regex=False).str.strip()
    eff_numeric = pd.to_numeric(eff_series, errors="coerce").dropna()
    if eff_numeric.empty:
        avg_eff = "0%"
    else:
        mean_eff = float(eff_numeric.mean())
        avg_eff = f"{(mean_eff * 100.0 if mean_eff <= 1.5 else mean_eff):.0f}%"

    total_plan_qty = float(df["Plan Qty"].sum() or 0)

    return str(active_lines), str(active_orders), avg_eff, _format_plan_qty(total_plan_qty)


@callback(
    [Output("live-planner-store", "data"), Output("live-planner-status", "children"), Output("live-planner-status", "color"), Output("live-planner-table", "children")],
    [Input("live-planner-refresh", "n_intervals")],
    [State("live-planner-store", "data")],
)
def refresh_live_planner_feed(n_intervals, current_rows):
    try:
        # Show loading status
        if n_intervals > 0:
            print(f"\n[INFO] Fetching live BPO data at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        live_rows = _fetch_live_planner_records(force_refresh=(n_intervals or 0) > 0)
        
        if not live_rows:
            cached_rows = current_rows if isinstance(current_rows, list) and current_rows else _load_live_planner_cache()
            if cached_rows:
                msg = dbc.Alert(
                    [html.Span("⚠️ "), "No new records found, showing cached current-date data"],
                    color="warning",
                    className="mb-0"
                )
                return cached_rows, msg, "warning", _build_live_planner_table(cached_rows)
            msg = dbc.Alert(
                [html.Span("ℹ️ "), "Waiting for live BPO updates..."],
                color="secondary",
                className="mb-0"
            )
            return [], msg, "secondary", dbc.Alert("No current-date updates found yet. Check again later.", color="secondary")

        duplicate_count = sum(1 for row in live_rows if _normalize_po(_get_plan_number(row)) in {_normalize_po(_get_plan_number(plan)) for plan in SAVED_PLANS if isinstance(plan, dict)})
        pending_count = max(0, len(live_rows) - duplicate_count)
        
        msg = dbc.Alert(
            [
                html.Span("✅ "),
                f"Live sync successful: {len(live_rows)} BPO(s) loaded (current date). {pending_count} pending AI approval, {duplicate_count} already in plans."
            ],
            color="success",
            className="mb-0"
        )
        _save_live_planner_cache(live_rows)
        return live_rows, msg, "success", _build_live_planner_table(live_rows)
        
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(f"\n[ERROR] Network/API error fetching live data: {type(exc).__name__}: {exc}")
        fallback_rows = current_rows if isinstance(current_rows, list) else []
        if not fallback_rows:
            fallback_rows = _load_live_planner_cache()
        
        if fallback_rows:
            msg = dbc.Alert(
                [
                    html.Span("🔄 "),
                    f"Live feed is slow (using cached current-date data). {type(exc).__name__}: {str(exc)[:50]}..."
                ],
                color="warning",
                className="mb-0"
            )
            print(f"[WARNING] Using cached data fallback. Cached rows: {len(fallback_rows)}")
            return fallback_rows, msg, "warning", _build_live_planner_table(fallback_rows)
        
        msg = dbc.Alert(
            [
                html.Span("❌ "),
                f"Live feed temporarily unavailable. {type(exc).__name__}: {str(exc)[:80]}... Please try again in a moment."
            ],
            color="danger",
            className="mb-0"
        )
        print(f"[ERROR] No cache available and API failed")
        return [], msg, "danger", dbc.Alert("Live feed is temporarily unavailable. Please try again soon.", color="danger")
        
    except Exception as exc:
        print(f"\n[ERROR] Unexpected error fetching live data: {type(exc).__name__}: {exc}")
        fallback_rows = current_rows if isinstance(current_rows, list) else []
        if not fallback_rows:
            fallback_rows = _load_live_planner_cache()
        
        if fallback_rows:
            msg = dbc.Alert(
                [
                    html.Span("🔄 "),
                    f"Live feed encountered an issue (using cached data). {type(exc).__name__}: {str(exc)[:50]}..."
                ],
                color="warning",
                className="mb-0"
            )
            return fallback_rows, msg, "warning", _build_live_planner_table(fallback_rows)
        
        msg = dbc.Alert(
            [
                html.Span("❌ "),
                f"Unexpected error. {type(exc).__name__}: {str(exc)[:80]}..."
            ],
            color="danger",
            className="mb-0"
        )
        return [], msg, "danger", dbc.Alert("An unexpected error occurred. Please refresh the page.", color="danger")


@callback(
    [Output("ai-train-status", "children"), Output("ai-train-status", "color")],
    Input("ai-train-btn", "n_clicks"),
    prevent_initial_call=True,
)
def train_models_callback(_):
    try:
        stats = train_ai_models(EXCEL_PATH)
        _load_encoder_cache()
        message = (
            f"✅ Training complete: {stats['rows']} rows, {stats['classes']} line classes, "
            f"line acc={stats['line_train_acc']:.2%}, days MAE={stats['days_train_mae']:.2f}."
        )
        return message, "success"
    except Exception as exc:
        return f"❌ Training failed: {exc}", "danger"


@callback(
    [
        Output("ai-predict-output", "children"),
        Output("ai-predict-output", "color"),
        Output("prediction-results-container", "children"),
        Output("pending-prediction-store", "data"),
    ],
    Input("live-planner-store", "data"),
    State("pending-prediction-store", "data"),
    prevent_initial_call=True,
)
def predict_plan_callback(live_rows, pending_row):
    global PREDICTION_QUEUE
    try:
        if pending_row:
            return no_update, no_update, no_update, no_update

        if not isinstance(live_rows, list) or not live_rows:
            msg = "Waiting for current-date API data to auto-generate prediction."
            PREDICTION_QUEUE = []
            return msg, "secondary", dbc.Alert(msg, color="secondary"), None

        saved_po_keys = {
            _normalize_po(_get_plan_number(plan))
            for plan in SAVED_PLANS
            if isinstance(plan, dict)
        }

        candidate_rows = []
        for row in live_rows:
            po_try = _normalize_po(_get_plan_number(row))
            if po_try and po_try not in saved_po_keys:
                candidate_rows.append(row)

        if not candidate_rows:
            msg = "No pending current-date BPO Number for AI approval."
            PREDICTION_QUEUE = []
            return msg, "secondary", dbc.Alert(msg, color="secondary"), None

        model_line, model_days, encoders, meta = _load_artifacts()
        defaults = meta.get("defaults", {}) if isinstance(meta, dict) else {}

        prediction_queue = []
        blocked_count = 0

        for candidate in candidate_rows:
            po_number = _get_plan_number(candidate)
            sheet_inputs = _lookup_inputs_by_po(po_number)
            live_inputs = candidate
            sale_order_creation_date = _get_live_sale_order_creation_date(live_inputs)

            customer = live_inputs.get("customer") or sheet_inputs.get("customer")
            style = live_inputs.get("style") or sheet_inputs.get("style")
            product = live_inputs.get("product") or sheet_inputs.get("product") or "New"
            sam = live_inputs.get("sam") if live_inputs.get("sam") is not None else sheet_inputs.get("sam")
            plan_qty = live_inputs.get("plan_qty") if live_inputs.get("plan_qty") is not None else sheet_inputs.get("plan_qty")

            missing = []
            if not customer:
                missing.append("Cstmr")
            if not style:
                missing.append("Style")
            if not product:
                missing.append("Product")
            if sam is None:
                missing.append("SAM")
            if plan_qty is None:
                missing.append("Qty")

            if sam is not None and float(sam) <= 0:
                missing.append("SAM must be > 0")
            if plan_qty is not None and float(plan_qty) <= 0:
                missing.append("Qty must be > 0")

            if missing:
                blocked_count += 1
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
                "Cstmr": _encode_value(encoders["Cstmr"], customer, "customer", defaults.get("Cstmr")),
                "Style": _encode_value(encoders["Style"], style, "style", defaults.get("Style")),
                "Product": _encode_value(encoders["Product"], product, "product", defaults.get("Product")),
                "Fabric": _encode_value(encoders["Fabric"], fabric, "fabric", defaults.get("Fabric")),
                "wash Type": _encode_value(encoders["wash Type"], wash_type, "wash type", defaults.get("wash Type")),
                "Color": _encode_value(encoders["Color"], color, "color", defaults.get("Color")),
                "SAM": float(sam),
                "Plan Qty": float(plan_qty),
                "Pln Eff Num": float(pln_eff_num),
                "Bal Sew": float(bal_sew),
            }

            X_pred = pd.DataFrame([row], columns=FEATURES)
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

            pred_row = _build_prediction_row(
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

            operation_hint = po_inputs.get("operation") or po_inputs.get("process") or po_inputs.get("op")
            top_resource_recos = _recommend_resources(
                pred_line=str(pred_line),
                style=style,
                customer=customer,
                operation=operation_hint,
                top_n=3,
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

        if not prediction_queue:
            msg = f"No eligible BPO for prediction. {blocked_count} blocked due to missing fields."
            PREDICTION_QUEUE = []
            return msg, "warning", dbc.Alert(msg, color="warning"), None

        first_pending = prediction_queue[0]
        remaining_queue = prediction_queue[1:]
        PREDICTION_QUEUE = remaining_queue
        top3_text = ", ".join([f"{item['line']} ({item['score'] * 100:.1f}%)" for item in first_pending.get("top_line_recos", [])])
        pred_days = int(first_pending.get("pred_days", 0) or 0)
        pred_end_date = (datetime.now() + timedelta(days=pred_days)).strftime("%d-%b-%Y") if pred_days > 0 else "N/A"
        po_number = str(first_pending.get("po_number", ""))
        pred_line = str(first_pending.get("pred_line", ""))
        status_msg = (
            f"✅ Auto-predicted {len(prediction_queue)} BPO(s). Now reviewing: {po_number} | "
            f"Recommended Line: {pred_line} | Top 3 Lines: {top3_text} | Estimated Days: {pred_days} | Expected End: {pred_end_date}"
        )
        return status_msg, "success", _build_prediction_review_card(first_pending, len(remaining_queue)), first_pending
    except Exception as exc:
        PREDICTION_QUEUE = []
        return f"❌ Prediction failed: {exc}", "danger", dbc.Alert(f"Error: {exc}", color="danger"), None


@callback(
    [
        Output("prediction-results-container", "children", allow_duplicate=True),
        Output("pending-prediction-store", "data", allow_duplicate=True),
        Output("nav-dashboard", "n_clicks", allow_duplicate=True),
        Output("ai-predict-output", "children", allow_duplicate=True),
        Output("ai-predict-output", "color", allow_duplicate=True),
        Output("prediction-approval-click-state", "data", allow_duplicate=True),
    ],
    [Input("prediction-approve-btn", "n_clicks"), Input("prediction-reject-btn", "n_clicks")],
    [
        State("pending-prediction-store", "data"),
        State("nav-dashboard", "n_clicks"),
        State("prediction-approval-click-state", "data"),
    ],
    prevent_initial_call=True,
)
def handle_prediction_approval(ok_clicks, no_clicks, pending_payload, nav_dashboard_clicks, click_state):
    global PREDICTION_QUEUE
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update, no_update, no_update, no_update, no_update, no_update

    click_state = click_state or {"ok": 0, "no": 0}
    queue_rows = PREDICTION_QUEUE if isinstance(PREDICTION_QUEUE, list) else []
    last_ok = int(click_state.get("ok", 0) or 0)
    last_no = int(click_state.get("no", 0) or 0)

    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    if not pending_payload:
        return dbc.Alert("No pending prediction to process.", color="warning"), None, no_update, "No pending prediction.", "warning", click_state

    pending_row = pending_payload.get("pred_row", {}) if isinstance(pending_payload, dict) else {}
    pending_po = _normalize_po(_get_plan_number(pending_row))

    if trigger == "prediction-approve-btn":
        current_ok = int(ok_clicks or 0)
        # Proceed only when a new explicit click happened.
        if current_ok <= last_ok:
            return no_update, no_update, no_update, no_update, no_update, no_update

        if pending_po:
            PREDICTION_RESULTS[:] = [row for row in PREDICTION_RESULTS if _normalize_po(_get_plan_number(row)) != pending_po]
        PREDICTION_RESULTS.insert(0, pending_row)
        if len(PREDICTION_RESULTS) > 5:
            PREDICTION_RESULTS.pop()

        _upsert_saved_plan_row(pending_row)
        _persist_saved_plans()

        next_state = {"ok": current_ok, "no": last_no}

        if queue_rows:
            next_pending = queue_rows[0]
            remaining_queue = queue_rows[1:]
            PREDICTION_QUEUE = remaining_queue
            next_po = str(next_pending.get("po_number", ""))
            msg = f"✅ Saved {pending_po or 'prediction'}. Next BPO ready: {next_po}. Remaining: {len(queue_rows)}"
            return _build_prediction_review_card(next_pending, len(remaining_queue)), next_pending, no_update, msg, "success", next_state

        PREDICTION_QUEUE = []
        return dbc.Alert("✅ Prediction saved. All pending BPO predictions are processed.", color="success"), None, no_update, "All pending predictions processed.", "success", next_state

    if trigger == "prediction-reject-btn":
        current_no = int(no_clicks or 0)
        if current_no <= last_no:
            return no_update, no_update, no_update, no_update, no_update, no_update

        next_state = {"ok": last_ok, "no": current_no}
        if queue_rows:
            next_pending = queue_rows[0]
            remaining_queue = queue_rows[1:]
            PREDICTION_QUEUE = remaining_queue
            next_po = str(next_pending.get("po_number", ""))
            msg = f"Prediction discarded. Next BPO ready: {next_po}. Remaining: {len(queue_rows)}"
            return _build_prediction_review_card(next_pending, len(remaining_queue)), next_pending, no_update, msg, "secondary", next_state

        PREDICTION_QUEUE = []
        return dbc.Alert("Prediction discarded. No more pending predictions.", color="secondary"), None, no_update, "Prediction discarded.", "secondary", next_state

    return no_update, no_update, no_update, no_update, no_update, no_update


@callback(
    [Output("order-tracker-container", "children"), Output("order-analysis-container", "children"), Output("order-search-meta", "children")],
    [Input("order-search-input", "value"), Input("saved-plans-refresh", "data")],
)
def search_order_tracker(query, _):
    if not query or not str(query).strip():
        return (
            html.Div(),
            html.Div(),
            dbc.Badge("Waiting for search", color="secondary")
        )

    q = str(query).strip().lower()
    matched_orders = []

    # Search both: sample live orders + saved plan history orders
    orders_to_search = list(orders) + _saved_plans_as_orders()
    for order in orders_to_search:
        search_text = " ".join([
            str(order.get("bpo", order.get("po", ""))),
            str(order.get("customer", "")),
            str(order.get("style", "")),
            str(order.get("line", "")),
        ]).lower()
        if q in search_text:
            matched_orders.append(order)

    if not matched_orders:
        return (
            dbc.Alert("No order matched your search. Try BPO Number or customer name.", color="warning"),
            dbc.Alert("Analysis unavailable because no order matched.", color="warning"),
            dbc.Badge("0 match", color="danger")
        )

    tracker_ui = build_order_tracker(matched_orders)
    if len(matched_orders) == 1:
        analysis_ui = build_order_analysis(matched_orders[0])
    else:
        total_remaining_days = 0
        for order in matched_orders:
            order_stages = order.get("stages", [])
            done_lead = sum(int(stage.get("lead_days", 0)) for stage in order_stages if stage.get("status") == "done")
            total_lead = sum(int(stage.get("lead_days", 0)) for stage in order_stages)
            total_remaining_days += max(0, total_lead - done_lead)

        analysis_ui = dbc.Alert(
            f"{len(matched_orders)} orders matched. Combined remaining lead time: {total_remaining_days} days. For detailed analysis, narrow search to one order.",
            color="info"
        )

    return tracker_ui, analysis_ui, dbc.Badge(f"{len(matched_orders)} match(es)", color="primary")


@callback(
    [Output("ppc-filtered-table-container", "children"), Output("ppc-month-filter", "options"), Output("ppc-month-filter-status", "children")],
    [Input("ppc-month-filter", "value"), Input("ppc-bpo-search", "value"), Input("saved-plans-refresh", "data")],
)
def update_ppc_month_view(month_value, bpo_query, __):
    options = _get_month_options()
    df = _get_saved_plans_df(month_value)

    bpo_query_text = str(bpo_query or "").strip().upper()
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
        return dbc.Alert("No saved plans available for selected filter.", color="warning"), options, dbc.Badge(f"{label} | 0 plans", color="secondary")

    for required in ["Line #", "BPO Number", "PO#", "Cstmr", "Style", "SAM", "Plan Qty", "Pln Eff %", "P.Dy Cpcty", "Com Dys Wk", "EX-MILL", "Created At"]:
        if required not in df.columns:
            df[required] = ""

    # Keep table grouped and ordered by line first, then latest plans within each line.
    line_numbers = df["Line #"].astype(str).str.extract(r"(\d+)", expand=False)
    df["_line_sort"] = pd.to_numeric(line_numbers, errors="coerce").fillna(10**6)
    if "Created At" in df.columns:
        df = df.sort_values(by=["_line_sort", "Line #", "Created At"], ascending=[True, True, False])
    else:
        df = df.sort_values(by=["_line_sort", "Line #"], ascending=[True, True])

    month_stats = _month_workday_stats(month_value)
    line_machines = 58
    working_mins_per_day = 480
    available_sam = month_stats["work_days"] * line_machines * working_mins_per_day

    grouped_rows = []
    for line_value, group in df.groupby(df["Line #"].astype(str), sort=False):
        planned_qty = float(pd.to_numeric(group["Plan Qty"], errors="coerce").fillna(0).sum())
        avg_sam = float(pd.to_numeric(group["SAM"], errors="coerce").dropna().mean() or 0.0)

        # Use actual Pln Eff % from data, ensure at least 75%
        eff_raw = group["Pln Eff %"].astype(str).str.replace("%", "", regex=False).str.strip()
        eff_numeric = pd.to_numeric(eff_raw, errors="coerce").dropna()
        if not eff_numeric.empty:
            avg_eff = float(eff_numeric.mean())
            # Convert to percentage if needed (e.g., 0.75 -> 75%)
            planned_eff_pct = avg_eff * 100.0 if avg_eff <= 1.5 else avg_eff
        else:
            planned_eff_pct = 75.0
        # Ensure minimum 75% planned efficiency
        planned_eff_pct = max(75.0, float(planned_eff_pct))

        produced_sam = planned_qty * avg_sam
        work_days = int(month_stats["work_days"])
        per_day_cap = (planned_qty / work_days) if work_days > 0 else 0.0
        grouped_rows.append({
            "SR#": None,
            "Line": str(line_value),
            "Planned Quantity": int(round(planned_qty)),
            "Average SAM": round(avg_sam, 1),
            "Planned Efficiency": f"{planned_eff_pct:.0f}%",
            "Per day Capacity": int(round(per_day_cap)),
            "Work Days": work_days,
            "Sundays": int(month_stats["sundays"]),
            "Holiday": int(month_stats["holiday"]),
            "Month Days": int(month_stats["month_days"]),
            "Available SAM": int(available_sam),
            "Produced SAM": int(round(produced_sam)),
        })

    table_df = pd.DataFrame(grouped_rows)
    table_df["SR#"] = range(1, len(table_df) + 1)

    table_rows = []
    for _, row in table_df.iterrows():
        line_text = str(row.get("Line", ""))
        table_rows.append(
            html.Tr([
                html.Td(str(row.get("SR#", ""))),
                html.Td(dbc.Button(line_text, id={"type": "line-detail-btn", "line": line_text}, color="link", style={"padding": "0", "fontWeight": "700"})),
                html.Td(str(row.get("Planned Quantity", ""))),
                html.Td(f"{float(row.get('Average SAM', 0) or 0):.1f}"),
                html.Td(str(row.get("Planned Efficiency", ""))),
                html.Td(str(row.get("Per day Capacity", ""))),
                html.Td(str(row.get("Work Days", ""))),
                html.Td(str(row.get("Sundays", ""))),
                html.Td(str(row.get("Holiday", ""))),
                html.Td(str(row.get("Month Days", ""))),
                html.Td(str(row.get("Available SAM", ""))),
                html.Td(str(row.get("Produced SAM", ""))),
            ])
        )

    compact_table = dbc.Table([
        html.Thead(html.Tr([
            html.Th("SR#"),
            html.Th("Line"),
            html.Th("Planned Quantity"),
            html.Th("Average SAM"),
            html.Th("Planned Efficiency"),
            html.Th("Per day Capacity"),
            html.Th("Work Days"),
            html.Th("Sundays"),
            html.Th("Holiday"),
            html.Th("Month Days"),
            html.Th("Available SAM"),
            html.Th("Produced SAM"),
        ])),
        html.Tbody(table_rows),
    ], striped=True, bordered=True, hover=True, responsive=True)

    label = "All months" if not month_value else f"Month: {month_value}"
    if bpo_query_text:
        label = f"{label} | BPO Number: {bpo_query_text}"
    return compact_table, options, dbc.Badge(f"{label} | {len(table_df)} line(s)", color="info")


@callback(
    [Output("ppc-download-excel", "data"), Output("ppc-download-status", "children"), Output("ppc-download-status", "color"), Output("ppc-download-status", "is_open")],
    Input("ppc-download-excel-btn", "n_clicks"),
    [State("ppc-month-filter", "value"), State("ppc-bpo-search", "value")],
    prevent_initial_call=True,
)
def download_filtered_plans(_, month_value, bpo_query):
    df = _get_saved_plans_df(month_value)
    bpo_query_text = str(bpo_query or "").strip().upper()

    if bpo_query_text:
        if "BPO Number" not in df.columns and "PO#" in df.columns:
            df["BPO Number"] = df["PO#"]
        if "BPO Number" not in df.columns:
            df["BPO Number"] = ""
        bpo_series = df["BPO Number"].astype(str).str.upper()
        df = df[bpo_series.str.contains(bpo_query_text, na=False)]

    if df.empty:
        return no_update, "No data to download for selected filter.", "warning", True

    safe_month = (month_value or "all_months").replace(" ", "_")
    safe_bpo = bpo_query_text.replace(" ", "_") if bpo_query_text else "all_bpo"
    file_name = f"ppc_plan_{safe_month}_{safe_bpo}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return dcc.send_data_frame(df.to_excel, file_name, sheet_name="PPC Plan", index=False), f"Excel download ready: {file_name}", "success", True


@callback(
    [Output("bpo-details-modal", "is_open"), Output("bpo-details-modal-title", "children"), Output("bpo-details-modal-body", "children")],
    [Input({"type": "bpo-detail-btn", "index": ALL}, "n_clicks"), Input("bpo-details-close", "n_clicks")],
    [State({"type": "bpo-detail-btn", "index": ALL}, "id"), State("bpo-details-modal", "is_open")],
    prevent_initial_call=True,
)
def show_bpo_details(button_clicks, close_clicks, ids, is_open):
    ctx = dash.callback_context
    if not ctx.triggered:
        return is_open, no_update, no_update

    prop_id = ctx.triggered[0]["prop_id"]
    if prop_id.startswith("bpo-details-close"):
        return False, no_update, no_update

    trigger_id_json = prop_id.split(".")[0]
    try:
        trigger_id = json.loads(trigger_id_json)
        row_key = str(trigger_id.get("index", ""))
    except Exception:
        return is_open, no_update, no_update

    # Only open modal when this was a real user click.
    # Dash can trigger this callback when buttons are created/re-rendered (e.g., refresh / filter)
    # where n_clicks is None/0; ignore those events.
    try:
        trigger_idx = next((i for i, btn_id in enumerate(ids or []) if btn_id == trigger_id), None)
    except Exception:
        trigger_idx = None

    if trigger_idx is None:
        return is_open, no_update, no_update

    try:
        click_value = (button_clicks or [])[trigger_idx]
    except Exception:
        click_value = None

    if not click_value:
        return is_open, no_update, no_update

    plans_df = _get_saved_plans_df()
    if plans_df.empty:
        return False, "Plan Details", dbc.Alert("No saved plan data available.", color="warning")

    if "Created At" not in plans_df.columns:
        plans_df["Created At"] = ""
    if "BPO Number" not in plans_df.columns and "PO#" in plans_df.columns:
        plans_df["BPO Number"] = plans_df["PO#"]
    if "BPO Number" not in plans_df.columns:
        plans_df["BPO Number"] = ""

    plans_df["_row_key"] = plans_df["Created At"].astype(str) + "|" + plans_df["BPO Number"].astype(str)
    match_df = plans_df[plans_df["_row_key"].astype(str) == row_key]
    if match_df.empty:
        return False, "Plan Details", dbc.Alert("Selected plan detail not found.", color="warning")

    row = match_df.iloc[0].to_dict()
    details_rows = []
    for key, value in row.items():
        if key == "_row_key":
            continue
        details_rows.append(html.Tr([html.Th(str(key), style={"width": "35%"}), html.Td(str(value))]))

    bpo_value = str(row.get("BPO Number", row.get("PO#", "Plan")))
    details_table = dbc.Table([html.Tbody(details_rows)], bordered=True, striped=True, hover=True)
    return True, f"Plan Details - {bpo_value}", details_table


@callback(
    Output("selected-line-store", "data"),
    Input({"type": "line-detail-btn", "line": ALL}, "n_clicks"),
    State({"type": "line-detail-btn", "line": ALL}, "id"),
    prevent_initial_call=True,
)
def select_line_detail(n_clicks, ids):
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update

    try:
        trigger_id = json.loads(ctx.triggered[0]["prop_id"].split(".")[0])
        trigger_idx = next((i for i, btn_id in enumerate(ids or []) if btn_id == trigger_id), None)
        if trigger_idx is None:
            return no_update

        click_value = (n_clicks or [])[trigger_idx] if n_clicks else None
        if not click_value:
            return no_update

        return str(trigger_id.get("line", "")).strip() or None
    except Exception:
        return no_update


@callback(
    [Output("line-details-title", "children"), Output("line-details-summary", "children"), Output("line-details-container", "children")],
    [Input("selected-line-store", "data"), Input("saved-plans-refresh", "data")],
    State("page-line-details", "style"),
)
def build_line_details(selected_line, _refresh_counter, page_line_style):
    trigger = ""
    try:
        trigger = dash.callback_context.triggered[0]["prop_id"].split(".")[0]
    except Exception:
        trigger = ""

    # Skip heavy refresh work when line-details page is hidden.
    if trigger == "saved-plans-refresh" and isinstance(page_line_style, dict) and page_line_style.get("display") == "none":
        return no_update, no_update, no_update

    if not selected_line:
        return "Line Details", "", dbc.Alert("Select a line from All Month Plans.", color="info")

    return _build_line_details_content(str(selected_line).strip(), _plan_history_signature())

    plans_df = _get_saved_plans_df()
    if plans_df.empty or "Line #" not in plans_df.columns:
        return f"Line Details - {selected_line}", "", dbc.Alert("No saved plan data available.", color="warning")

    fallback_line = None
    if not selected_line:
        line_series = plans_df["Line #"].astype(str).str.strip()
        non_empty_lines = [line for line in line_series.tolist() if line]
        fallback_line = non_empty_lines[0] if non_empty_lines else None
        selected_line = fallback_line

    if not selected_line:
        return "Line Details", "", dbc.Alert("Select a line from All Month Plans.", color="info")

    line_df = plans_df[plans_df["Line #"].astype(str) == str(selected_line)].copy()
    if line_df.empty:
        return f"Line Details - {selected_line}", "", dbc.Alert(f"No plans found for line {selected_line}.", color="warning")

    if "Created At" in line_df.columns:
        line_df = line_df.sort_values(by="Created At", ascending=False)

    # Stable row key used by Edit buttons.
    if "Created At" not in line_df.columns:
        line_df["Created At"] = ""
    if "BPO Number" not in line_df.columns and "PO#" in line_df.columns:
        line_df["BPO Number"] = line_df["PO#"]
    if "BPO Number" not in line_df.columns:
        line_df["BPO Number"] = ""
    line_df["_row_key"] = line_df.apply(lambda r: _row_key_from_plan_row(r.to_dict()), axis=1)

    # Per day capacity formula: ((58 * 480) / SAM) * plan efficiency
    if "SAM" in line_df.columns and "Pln Eff %" in line_df.columns:
        sam_series = pd.to_numeric(line_df["SAM"], errors="coerce")
        eff_raw = line_df["Pln Eff %"].astype(str).str.replace("%", "", regex=False).str.strip()
        eff_numeric = pd.to_numeric(eff_raw, errors="coerce")
        eff_factor = eff_numeric.where(eff_numeric <= 1.5, eff_numeric / 100.0)
        line_df["Per day capacity"] = (((58.0 * 480.0) / sam_series) * eff_factor).where(sam_series > 0, 0).fillna(0).round(0).astype(int)
    else:
        line_df["Per day capacity"] = 0

    # INDC Target formula: Strt Sw Out Dt - 5 days
    if "Strt Sw Out Dt" in line_df.columns:
        start_dates = pd.to_datetime(line_df["Strt Sw Out Dt"], format="%d-%b-%Y", errors="coerce")
        if start_dates.isna().all():
            start_dates = pd.to_datetime(line_df["Strt Sw Out Dt"], errors="coerce", dayfirst=True)
        line_df["INDC Target"] = (start_dates - pd.to_timedelta(5, unit="D")).dt.strftime("%d-%b-%Y").fillna("")
    else:
        line_df["INDC Target"] = ""

    # EX-Mill display column: expected_shipment_date first, then EX-MILL, then exMill fallback.
    line_df["EX-Mill"] = ""
    if "expected_shipment_date" in line_df.columns:
        line_df["EX-Mill"] = line_df["expected_shipment_date"].fillna("").astype(str).str.strip()
    if "EX-MILL" in line_df.columns:
        fallback_exmill = line_df["EX-MILL"].fillna("").astype(str).str.strip()
        primary_exmill = line_df["EX-Mill"].fillna("").astype(str).str.strip()
        line_df["EX-Mill"] = primary_exmill.where(primary_exmill != "", fallback_exmill)
    if "exMill" in line_df.columns:
        fallback_exmill_camel = line_df["exMill"].fillna("").astype(str).str.strip()
        primary_exmill = line_df["EX-Mill"].fillna("").astype(str).str.strip()
        line_df["EX-Mill"] = primary_exmill.where(primary_exmill != "", fallback_exmill_camel)

    detail_columns = [
        ("BPO Number", "BPO Number"),
        ("Cstmr", "Customer"),
        ("Style", "Style"),
        ("Plan Qty", "Plan Qty"),
        ("SAM", "SAM"),
        ("Pln Eff %", "Plan Eff %"),
        ("Per day capacity", "Per Day Capacity"),
        ("INDC Target", "INDC Target"),
        ("Strt Sw Out Dt", "Start Sew Out Date"),
        ("End Sew Date", "End Sew Date"),
        ("EX-Mill", "EX-Mill"),
        ("Created At", "Created At"),
    ]

    def _format_line_value(source_col, raw_value):
        if source_col == "SAM":
            sam_num = pd.to_numeric(pd.Series([raw_value]), errors="coerce").iloc[0]
            return f"{float(sam_num):.1f}" if pd.notna(sam_num) else str(raw_value)

        if source_col in {"Plan Qty", "Per day capacity"}:
            num = pd.to_numeric(pd.Series([raw_value]), errors="coerce").iloc[0]
            return str(int(round(float(num)))) if pd.notna(num) else str(raw_value)

        if source_col == "Pln Eff %":
            text = str(raw_value or "").strip().replace("%", "")
            num = pd.to_numeric(pd.Series([text]), errors="coerce").iloc[0]
            if pd.isna(num):
                return str(raw_value)
            eff_pct = float(num) * 100.0 if float(num) <= 1.5 else float(num)
            return f"{int(round(eff_pct))}%"

        return str(raw_value)

    rows = []
    for _, row in line_df.iterrows():
        row_key = str(row.get("_row_key", "")).strip()
        edit_btn = dbc.Button(
            "Edit",
            id={"type": "edit-bpo-btn", "row_key": row_key},
            color="primary",
            size="sm",
        )
        rows.append(
            html.Tr(
                [
                    *[html.Td(_format_line_value(source_col, row.get(source_col, ""))) for source_col, _ in detail_columns],
                    html.Td(edit_btn),
                ]
            )
        )

    details_table = dbc.Table([
        html.Thead(html.Tr([*([html.Th(display_label) for _, display_label in detail_columns]), html.Th("Action")])) ,
        html.Tbody(rows),
    ], bordered=True, striped=True, hover=True, responsive=True)

    active_resources_df, reserve_resources_df, resource_stats = _get_line_active_resources(selected_line, capacity=58)
    if active_resources_df.empty:
        resources_panel = dbc.Alert(f"No skill-matrix resource mapping found for line {selected_line}.", color="secondary", className="mb-0")
    else:
        resource_rows = []
        for _, resource_row in active_resources_df.iterrows():
            resource_rows.append(
                html.Tr([
                    html.Td(str(resource_row.get("resource_name", ""))),
                    html.Td(str(resource_row.get("resource_code", ""))),
                    html.Td(str(resource_row.get("line_name", ""))),
                    html.Td(f"{float(resource_row.get('efficiency_score', 0) or 0):.0f}%"),
                    html.Td(f"{float(resource_row.get('skill_level_score', 0) or 0):.0f}%"),
                    html.Td(str(resource_row.get("availability_state", ""))),
                    html.Td(str(resource_row.get("availability", ""))),
                    html.Td(str(resource_row.get("current_line", ""))),
                    html.Td(str(resource_row.get("operation_name", ""))),
                ])
            )

        resources_table = dbc.Table([
            html.Thead(html.Tr([
                html.Th("Resource"),
                html.Th("Code"),
                html.Th("Line"),
                html.Th("Efficiency"),
                html.Th("Skill"),
                html.Th("Status"),
                html.Th("Availability"),
                html.Th("Current Line"),
                html.Th("Operation"),
            ])),
            html.Tbody(resource_rows),
        ], bordered=True, striped=True, hover=True, responsive=True)

        resource_eff_avg = pd.to_numeric(active_resources_df["efficiency_score"], errors="coerce").fillna(0).mean() if "efficiency_score" in active_resources_df.columns else 0
        resource_skill_avg = pd.to_numeric(active_resources_df["skill_level_score"], errors="coerce").fillna(0).mean() if "skill_level_score" in active_resources_df.columns else 0

        resources_panel = html.Div([
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div("Active Resources", className="text-muted small"),
                    html.Div(f"{resource_stats['active_count']}/{resource_stats['capacity']}", className="kpi-value text-info", style={"fontSize": "24px"}),
                ], className="resource-chip-muted"), md=4),
                dbc.Col(html.Div([
                    html.Div("Unavailable", className="text-muted small"),
                    html.Div(str(resource_stats["unavailable_count"]), className="kpi-value text-danger", style={"fontSize": "24px"}),
                ], className="resource-chip-muted"), md=4),
                dbc.Col(html.Div([
                    html.Div("Reserve Replacements", className="text-muted small"),
                    html.Div(str(resource_stats["reserve_count"]), className="kpi-value text-warning", style={"fontSize": "24px"}),
                ], className="resource-chip-muted"), md=4),
            ], className="g-2 mb-3"),
            dbc.Alert(
                f"Active list shows top {resource_stats['capacity']} available/unknown resources. If someone is unavailable, replacement is picked from {resource_stats['reserve_count']} reserve resources.",
                color="light",
                className="mb-2",
            ),
            html.Div(resources_table, className="resource-table-wrap"),
        ], className="resource-card")

    summary = dbc.Alert([
        html.Div(f"{len(line_df)} order(s) running on {selected_line}.", className="mb-1"),
        html.Div(
            f"Active resources: {resource_stats.get('active_count', 0)}/{resource_stats.get('capacity', 58)} | Unavailable in mapped pool: {resource_stats.get('unavailable_count', 0)} | Reserve replacements: {resource_stats.get('reserve_count', 0)}",
            className="small text-muted",
        ),
        html.Div(
            "Availability is provisional (no live availability feed)." if not resource_stats.get("has_explicit_availability") else "Availability includes explicit availability markers.",
            className="small text-muted",
        ),
        html.Div("Showing the latest available line context." if fallback_line else "", className="small text-muted"),
    ], color="info", className="mb-0")
    return f"Line Details - {selected_line}", summary, html.Div([
        details_table,
        html.Hr(className="my-3"),
        html.H5("Resources Working on This Line (Active 58)", className="section-title mb-2"),
        resources_panel,
    ])


@callback(
    [
        Output("edit-plan-modal", "is_open"),
        Output("edit-plan-row-key", "data"),
        Output("edit-created-at", "value"),
        Output("edit-bpo", "value"),
        Output("edit-line", "value"),
        Output("edit-customer", "value"),
        Output("edit-style", "value"),
        Output("edit-product", "value"),
        Output("edit-sam", "value"),
        Output("edit-plan-qty", "value"),
        Output("edit-eff", "value"),
        Output("edit-status", "value"),
        Output("edit-exmill", "value"),
        Output("edit-start", "value"),
        Output("edit-end", "value"),
        Output("edit-plan-alert", "children"),
        Output("edit-plan-alert", "color"),
        Output("edit-plan-alert", "is_open"),
    ],
    [Input({"type": "edit-bpo-btn", "row_key": ALL}, "n_clicks"), Input("edit-plan-cancel", "n_clicks")],
    [State({"type": "edit-bpo-btn", "row_key": ALL}, "id")],
    prevent_initial_call=True,
)
def open_edit_plan_modal(edit_clicks, cancel_clicks, ids):
    ctx = dash.callback_context
    if not ctx.triggered:
        return (no_update,) * 18

    trigger = ctx.triggered[0]["prop_id"].split(".")[0]
    if trigger == "edit-plan-cancel":
        return False, None, None, None, None, None, None, None, None, None, None, None, None, None, None, "", "secondary", False

    # Edit button click
    trigger_id_json = trigger
    try:
        trigger_id = json.loads(trigger_id_json)
    except Exception:
        return (no_update,) * 18

    try:
        trigger_idx = next((i for i, btn_id in enumerate(ids or []) if btn_id == trigger_id), None)
    except Exception:
        trigger_idx = None
    if trigger_idx is None:
        return (no_update,) * 18

    try:
        click_value = (edit_clicks or [])[trigger_idx]
    except Exception:
        click_value = None
    if not click_value:
        return (no_update,) * 18

    row_key = str(trigger_id.get("row_key", "") or "").strip()
    if not row_key:
        return (no_update,) * 18

    df = _get_saved_plans_df()
    if df.empty:
        return False, None, None, None, None, None, None, None, None, None, None, None, None, None, None, "No saved plan data available.", "warning", True

    if "Created At" not in df.columns:
        df["Created At"] = ""
    if "BPO Number" not in df.columns and "PO#" in df.columns:
        df["BPO Number"] = df["PO#"]
    if "BPO Number" not in df.columns:
        df["BPO Number"] = ""
    df["_row_key"] = df.apply(lambda r: _row_key_from_plan_row(r.to_dict()), axis=1)
    match = df[df["_row_key"].astype(str) == row_key]
    if match.empty:
        return False, None, None, None, None, None, None, None, None, None, None, None, None, None, None, "Selected plan not found.", "warning", True

    row = match.iloc[0].to_dict()
    return (
        True,
        row_key,
        row.get("Created At", ""),
        row.get("BPO Number", row.get("PO#", "")),
        row.get("Line #", ""),
        row.get("Cstmr", ""),
        row.get("Style", ""),
        row.get("Product", ""),
        row.get("SAM", None),
        row.get("Plan Qty", None),
        row.get("Pln Eff %", ""),
        row.get("PPC Status", ""),
        row.get("EX-MILL", ""),
        row.get("Strt Sw Out Dt", ""),
        row.get("End Sew Date", ""),
        "",
        "secondary",
        False,
    )


@callback(
    [
        Output("edit-plan-modal", "is_open", allow_duplicate=True),
        Output("edit-plan-alert", "children", allow_duplicate=True),
        Output("edit-plan-alert", "color", allow_duplicate=True),
        Output("edit-plan-alert", "is_open", allow_duplicate=True),
        Output("saved-plans-refresh", "data", allow_duplicate=True),
    ],
    Input("edit-plan-save", "n_clicks"),
    [
        State("edit-plan-row-key", "data"),
        State("saved-plans-refresh", "data"),
        State("edit-bpo", "value"),
        State("edit-line", "value"),
        State("edit-customer", "value"),
        State("edit-style", "value"),
        State("edit-product", "value"),
        State("edit-sam", "value"),
        State("edit-plan-qty", "value"),
        State("edit-eff", "value"),
        State("edit-status", "value"),
        State("edit-exmill", "value"),
        State("edit-start", "value"),
        State("edit-end", "value"),
        State("edit-created-at", "value"),
    ],
    prevent_initial_call=True,
)
def save_edit_plan(_, row_key, refresh_counter, bpo, line, customer, style, product, sam, plan_qty, eff, status, exmill, start_dt, end_dt, created_at):
    if not row_key:
        return no_update, "No selected plan to update.", "warning", True, no_update

    sam_value = None
    if sam is not None and sam != "":
        try:
            sam_value = float(sam)
        except Exception:
            return no_update, "Invalid SAM value.", "warning", True, no_update

    qty_value = None
    if plan_qty is not None and plan_qty != "":
        try:
            qty_value = int(float(plan_qty))
        except Exception:
            return no_update, "Invalid Plan Qty value.", "warning", True, no_update

    # Update in memory list
    updated = False
    for i, plan in enumerate(SAVED_PLANS):
        if _row_key_from_plan_row(plan) == str(row_key):
            plan["BPO Number"] = str(bpo or "").strip()
            plan["PO#"] = str(bpo or "").strip()
            plan["Line #"] = str(line or "").strip()
            plan["Cstmr"] = str(customer or "").strip()
            plan["Style"] = str(style or "").strip()
            plan["Product"] = str(product or "").strip()
            plan["SAM"] = sam_value
            plan["Plan Qty"] = qty_value
            plan["Pln Eff %"] = str(eff or "").strip()
            plan["PPC Status"] = str(status or "").strip()
            plan["EX-MILL"] = str(exmill or "").strip()
            plan["Strt Sw Out Dt"] = str(start_dt or "").strip()
            plan["End Sew Date"] = str(end_dt or "").strip()
            # Keep Created At stable (displayed, not editable)
            if created_at is not None:
                plan["Created At"] = str(created_at)
            _upsert_saved_plan_row(plan)
            updated = True
            break

    if not updated:
        return no_update, "Plan not found (it may have been deleted).", "warning", True, no_update

    try:
        _persist_saved_plans()
    except Exception as exc:
        return no_update, f"Failed to save: {exc}", "danger", True, no_update

    next_refresh = int(refresh_counter or 0) + 1
    # Close modal after save; data refresh updates dashboard + line-details table.
    return False, "Saved.", "success", False, next_refresh


@callback(
    Output("selected-line-store", "data", allow_duplicate=True),
    Input("back-to-dashboard", "n_clicks"),
    prevent_initial_call=True,
)
def back_to_dashboard(_):
    return no_update


if __name__ == "__main__":
    # Default to localhost for safer development. Set PPC_HOST=0.0.0.0 only when LAN access is needed.
    host = str(os.getenv("PPC_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    live_reload = str(os.getenv("PPC_LIVE_RELOAD", "1")).strip().lower() in {"1", "true", "yes", "on"}
    app.run(
        host=host,
        port=8050,
        debug=live_reload,
        use_reloader=live_reload,
        dev_tools_hot_reload=live_reload,
    )
