import dash
from dash import html, Input, Output, State, callback, dcc
import dash_bootstrap_components as dbc
import pandas as pd
import joblib
import xgboost as xgb
from sklearn.preprocessing import LabelEncoder
from pathlib import Path
from datetime import datetime, timedelta

# ================== DATA ==================
orders = [
    {
        "po": "KBI-2602-00244", "customer": "KIABI", "line": "L#1-H", "style": "MGMW18PSLIM",
        "fabric": "NON DENIM, TWILL_315 PEACH BEIGE SIMP...", "wash": "Rinse", "color": "BEIGE SIMP",
        "sam": 12.26, "efficiency": "75%", "capacity": 1703, "planQty": 9319, "balSew": 1612,
        "ppcStatus": "Sewing", "indTarget": "22-Mar-2026", "exMill": "03-Apr-2026",
        "stages": [
            {"name": "PO Received", "status": "done", "date_completed": "19-Mar-2026", "lead_days": 0},
            {"name": "Fabric Clearance", "status": "done", "date_completed": "22-Mar-2026", "lead_days": 3},
            {"name": "Trims Cleared", "status": "done", "date_completed": "24-Mar-2026", "lead_days": 2},
            {"name": "Induction / Cut", "status": "done", "date_completed": "25-Mar-2026", "lead_days": 1},
            {"name": "Sew Start", "status": "current", "date_started": "27-Mar-2026", "lead_days": 2},
            {"name": "Sew Out", "status": "pending", "date_planned": "03-Apr-2026", "lead_days": 7},
            {"name": "EX-MILL", "status": "pending", "date_planned": "05-Apr-2026", "lead_days": 2}
        ]
    },
    {
        "po": "KBI-2602-00252", "customer": "KIABI", "line": "L#1-H", "style": "MGMW18PSLIM_V2",
        "fabric": "DENIM, TWILL_350", "wash": "Stone", "color": "BLUE",
        "sam": 10.5, "efficiency": "78%", "capacity": 1800, "planQty": 2870, "balSew": 300,
        "ppcStatus": "Induction Cut", "indTarget": "22-Mar-2026", "exMill": "10-Apr-2026",
        "stages": [
            {"name": "PO Received", "status": "done", "date_completed": "20-Mar-2026", "lead_days": 0},
            {"name": "Fabric Clearance", "status": "done", "date_completed": "23-Mar-2026", "lead_days": 3},
            {"name": "Trims Cleared", "status": "done", "date_completed": "25-Mar-2026", "lead_days": 2},
            {"name": "Induction / Cut", "status": "current", "date_started": "26-Mar-2026", "lead_days": 1},
            {"name": "Sew Start", "status": "pending", "date_planned": "29-Mar-2026", "lead_days": 3},
            {"name": "Sew Out", "status": "pending", "date_planned": "07-Apr-2026", "lead_days": 9},
            {"name": "EX-MILL", "status": "pending", "date_planned": "10-Apr-2026", "lead_days": 3}
        ]
    },
    {
        "po": "TWS-2511-02184", "customer": "TWO SOON", "line": "L#2 MZ", "style": "SOLID_BASIC",
        "fabric": "COTTON, JERSEY_250", "wash": "Pigment", "color": "BLACK",
        "sam": 8.2, "efficiency": "82%", "capacity": 2100, "planQty": 5150, "balSew": 50,
        "ppcStatus": "Planned", "indTarget": "28-Mar-2026", "exMill": "07-Apr-2026",
        "stages": [
            {"name": "PO Received", "status": "done", "date_completed": "18-Mar-2026", "lead_days": 0},
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
    {"po": "KBI-2602-00244", "cust": "KIABI", "inDate": "22-Mar-2026", "line": "L#1-H", "planQty": 9319, "status": "Cutting done", "statusCls": "success", "exMill": "03-Apr-2026"},
    {"po": "KBI-2602-00252", "cust": "KIABI", "inDate": "22-Mar-2026", "line": "L#1-H", "planQty": 2870, "status": "Cutting done", "statusCls": "success", "exMill": "10-Apr-2026"},
    # ... add all rows from your ppcRows array
])

# ================== AI PLANNER ==================
ROOT_DIR = Path(__file__).resolve().parent
EXCEL_PATH = ROOT_DIR / "data" / "Sewing loading Plan..xlsx"
MODEL_DIR = ROOT_DIR / "data" / "models"

FEATURES = ["Cstmr", "Style", "Product", "SAM", "Plan Qty"]
TARGETS = ["Line #", "TotalDays"]
CATEGORICAL_COLS = ["Cstmr", "Style", "Product", "Line #"]


def train_ai_models(excel_path: Path):
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    df = pd.read_excel(excel_path, sheet_name="Sewing Loading Plan", skiprows=2)
    required_cols = FEATURES + ["Line #", "Strt Sw Out Dt", "End Sew Date"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing columns in Excel: {', '.join(missing_cols)}")

    df["Strt Sw Out Dt"] = pd.to_datetime(df["Strt Sw Out Dt"], errors="coerce")
    df["End Sew Date"] = pd.to_datetime(df["End Sew Date"], errors="coerce")
    df["TotalDays"] = (df["End Sew Date"] - df["Strt Sw Out Dt"]).dt.days

    df_ml = df[FEATURES + TARGETS].dropna().copy()
    if df_ml.empty:
        raise ValueError("No usable rows after preprocessing. Check date and feature columns.")

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
        n_estimators=120,
        max_depth=6,
        learning_rate=0.1,
        eval_metric="mlogloss",
        random_state=42,
    )
    model_line.fit(X, y_line)
    model_line.save_model(str(MODEL_DIR / "ppc_line_model.json"))

    model_days = xgb.XGBRegressor(
        n_estimators=120,
        max_depth=6,
        learning_rate=0.1,
        objective="reg:squarederror",
        random_state=42,
    )
    model_days.fit(X, y_days)
    model_days.save_model(str(MODEL_DIR / "ppc_days_model.json"))

    return {
        "rows": len(df_ml),
        "classes": len(encoders["Line #"].classes_),
        "model_dir": str(MODEL_DIR),
    }


def _load_artifacts():
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

    return model_line, model_days, encoders


def _encode_value(le: LabelEncoder, value: str, col_name: str):
    val = str(value).strip()
    if val not in le.classes_:
        allowed = ", ".join(le.classes_[:8])
        raise ValueError(f"Unknown {col_name}: '{val}'. Example valid values: {allowed}")
    return le.transform([val])[0]


# Global cache for encoder classes to populate dropdowns
ENCODER_CACHE = {col: [] for col in CATEGORICAL_COLS}
PREDICTION_RESULTS = []  # Store prediction rows for the results table


def _load_encoder_cache():
    """Load encoder classes from saved files into cache for dropdown options."""
    global ENCODER_CACHE
    try:
        for col in CATEGORICAL_COLS:
            enc_path = MODEL_DIR / f"{col}_ppc_encoder.pkl"
            if enc_path.exists():
                le = joblib.load(enc_path)
                ENCODER_CACHE[col] = sorted(list(le.classes_))
        return True
    except Exception:
        return False


# Try loading existing encoders on startup
_load_encoder_cache()


def _build_prediction_row(
    customer: str,
    style: str,
    product: str,
    sam: float,
    plan_qty: float,
    pred_line: str,
    pred_days: int,
) -> dict:
    """Build a complete sewing plan row with formulas applied."""
    now = datetime.now()
    induction_date = now
    start_sew_date = now + timedelta(days=5)  # 5 days after induction
    end_sew_date = start_sew_date + timedelta(days=pred_days)
    
    # Formula calculations
    ple_efficiency = 0.75  # Default 75% planned efficiency
    working_mins_per_day = 480  # 8 hours * 60 minutes
    
    # Total stitches needed = Plan Qty * SAM
    ttl_stch = plan_qty * sam
    
    # Production capacity per day = (working_mins_per_day * ple_efficiency) / SAM
    p_dy_cpcty = (working_mins_per_day * ple_efficiency) / sam if sam > 0 else 0
    
    # Balance sew = remaining qty
    bal_sew = max(0, plan_qty - ttl_stch) if ttl_stch <= plan_qty else 0
    
    # Induction cut qty = Plan Qty (full qty for cutting)
    ind_cut_qty = plan_qty
    
    # Balance days remaining
    current_date = now
    bal_days = (end_sew_date - current_date).days
    
    row = {
        "Line #": pred_line,
        "PO#": "",
        "Cstmr": customer,
        "Style": style,
        "Product": product,
        "SAM": round(sam, 2),
        "Pln Eff %": f"{ple_efficiency*100:.1f}%",
        "P.Dy Cpcty": round(p_dy_cpcty, 0),
        "Ind /Cut Qty": int(ind_cut_qty),
        "Plan Qty": int(plan_qty),
        "Ttl Stch": round(ttl_stch, 0),
        "Bal Sew": int(bal_sew),
        "Com Dys Wk": pred_days,
        "Indc Target": induction_date.strftime("%d-%b-%Y"),
        "Strt Sw Out Dt": start_sew_date.strftime("%d-%b-%Y"),
        "End Sew Date": end_sew_date.strftime("%d-%b-%Y"),
        "PPC Status": "Planned",
        "Bal Days": bal_days,
        "EX-MILL": end_sew_date.strftime("%d-%b-%Y"),
        "EX-MILL wk": end_sew_date.strftime("%U"),
        "Ex-mill Mnth": end_sew_date.strftime("%b-%Y"),
        "Line Allocation": pred_line,
        "Old/New": product,
        "LT": pred_days,
    }
    return row

# ================== ORDER TRACKER HELPERS ==================
def _build_stage_flow(order: dict) -> html.Div:
    """Build visual stage flow timeline with lead times."""
    stages = order.get("stages", [])
    if not stages:
        return html.Div("No stages data")
    
    stage_elements = []
    for i, stage in enumerate(stages):
        status = stage.get("status", "pending")
        lead_days = stage.get("lead_days", 0)
        
        # Color based on status
        if status == "done":
            color = "#00e5a0"  # Green
            icon = "✓"
        elif status == "current":
            color = "#00c6ff"  # Cyan
            icon = "●"
        else:
            color = "#64748b"  # Gray
            icon = "○"
        
        stage_elem = html.Div([
            html.Div([
                html.Span(icon, style={"fontSize": "18px", "fontWeight": "700", "color": color}),
                html.Div(stage["name"], style={"fontSize": "11px", "fontWeight": "600", "marginTop": "4px"}),
                html.Div(f"{lead_days}d", style={"fontSize": "9px", "color": "#64748b", "marginTop": "2px"}),
            ], style={"textAlign": "center", "flex": "1"}),
        ], style={"display": "flex", "flexDirection": "column", "alignItems": "center"})
        
        stage_elements.append(stage_elem)
        
        # Add arrow between stages (except after last)
        if i < len(stages) - 1:
            arrow = html.Div("→", style={
                "fontSize": "16px",
                "color": "#1e2d4a",
                "padding": "0 8px",
                "display": "flex",
                "alignItems": "center"
            })
            stage_elements.append(arrow)\n    \n    return html.Div(stage_elements, style={\n        "display": "flex",\n        "alignItems": "center",\n        "justifyContent": "center",\n        "gap": "8px",\n        "padding": "16px",\n        "background": "#0a0e1a",\n        "borderRadius": "10px",\n        "marginBottom": "12px",\n        "overflow": "auto"\n    })\n\n\ndef _build_order_tracker() -> dbc.Card:\n    \"\"\"Build complete order tracker component with all active orders.\"\"\"\n    order_cards = []\n    \n    for order in orders:\n        current_stage = None\n        current_stage_idx = 0\n        for i, stage in enumerate(order.get(\"stages\", [])):\n            if stage.get(\"status\") == \"current\":\n                current_stage = stage\n                current_stage_idx = i\n                break\n        \n        # Find first non-done stage if no current\n        if not current_stage:\n            for i, stage in enumerate(order.get(\"stages\", [])):\n                if stage.get(\"status\") != \"done\":\n                    current_stage = stage\n                    current_stage_idx = i\n                    break\n        \n        status_color = \"success\" if order.get(\"ppcStatus\") == \"Completed\" else \"info\"\n        \n        card = dbc.Card([\n            dbc.CardBody([\n                html.Div([\n                    html.Div([\n                        html.Div(f\"PO: {order['po']}\", style={\"fontWeight\": \"700\", \"color\": \"#00c6ff\", \"fontSize\": \"14px\"}),\n                        html.Div(f\"Customer: {order['customer']} | Line: {order['line']}\", style={\"fontSize\": \"12px\", \"color\": \"#64748b\", \"marginTop\": \"4px\"}),\n                    ]),\n                    html.Div([\n                        dbc.Badge(order.get(\"ppcStatus\", \"Pending\"), color=status_color, className=\"ms-2\")\n                    ], style={\"textAlign\": \"right\"})\n                ], style={\"display\": \"flex\", \"justifyContent\": \"space-between\", \"marginBottom\": \"12px\"}),\n                \n                # Current Stage Info\n                html.Div([\n                    html.Div(f\"📍 Current: {current_stage['name'] if current_stage else 'N/A'}\", style={\"fontWeight\": \"600\", \"color\": \"#00c6ff\", \"marginBottom\": \"8px\", \"fontSize\": \"12px\"}),\n                    html.Div(f\"⏱️ Lead Time: {current_stage.get('lead_days', 0)} days\", style={\"fontSize\": \"11px\", \"color\": \"#00e5a0\"}),\n                ], style={\"padding\": \"8px\", \"background\": \"#111827\", \"borderRadius\": \"6px\", \"marginBottom\": \"12px\"}),\n                \n                # Stage Flow Timeline\n                _build_stage_flow(order),\n            ])\n        ], className=\"kpi-card\", style={\"marginBottom\": \"12px\"})\n        \n        order_cards.append(card)\n    \n    return html.Div(order_cards)\n\n# ================== APP ==================
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY],
                suppress_callback_exceptions=True,
                title="MG PPC Dashboard")

# Custom CSS (very close to your original)
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
            --red: #ff4757;
            --text: #e2e8f0;
            --muted: #64748b;
            --border: #1e2d4a;
        }
        body { background: var(--bg); color: var(--text); font-family: 'DM Sans', system-ui, sans-serif; }
        .brand { font-family: 'Rajdhani', sans-serif; font-size: 26px; font-weight: 700; 
                 background: linear-gradient(90deg, #00c6ff, #0072ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .nav-item { padding: 12px 14px; border-radius: 10px; cursor: pointer; color: var(--muted); }
        .nav-item.active, .nav-item:hover { background: rgba(0,198,255,0.15); color: var(--accent); }
        .kpi-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 20px; position: relative; }
        .kpi-value { font-family: 'Rajdhani', sans-serif; font-size: 32px; font-weight: 700; }
        .section-title { font-family: 'Rajdhani', sans-serif; font-size: 18px; font-weight: 600; }
        .line-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
        .eff-high { background: rgba(0,229,160,0.15); color: var(--green); }
        .eff-mid { background: rgba(255,193,7,0.15); color: var(--yellow); }
        .stage-dot { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
        .modal-content { background: var(--card); border: 1px solid var(--border); border-radius: 18px; }
    </style>
</head>
<body>
    {%app_entry%}
    <footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>
'''

# Sidebar
sidebar = html.Div([
    html.Div([
        html.Div("MG PPC", className="brand"),
        html.Div("Production Control", style={"fontSize": "11px", "color": "#64748b", "textTransform": "uppercase"})
    ], style={"padding": "28px 20px 20px", "borderBottom": "1px solid #1e2d4a"}),

    html.Div([
        html.Div([html.Span("📊", style={"marginRight": "12px"}), "Dashboard"], 
                 id="nav-dashboard", className="nav-item active", n_clicks=0),
        html.Div([html.Span("📋", style={"marginRight": "12px"}), "PPC Planner"], 
                 id="nav-ppc", className="nav-item", n_clicks=0),
        html.Div([html.Span("⚙️", style={"marginRight": "12px"}), "IE Planner"], 
                 id="nav-ie", className="nav-item", n_clicks=0),
    ], style={"padding": "24px 12px", "display": "flex", "flexDirection": "column", "gap": "6px"}),

    html.Div("Sewing Loading Plan<br>Apr 2026 · Active", 
             style={"padding": "16px 20px", "borderTop": "1px solid #1e2d4a", "fontSize": "11px", "color": "#64748b"}),
], style={"width": "220px", "background": "#0d1224", "position": "fixed", "height": "100vh", "borderRight": "1px solid #1e2d4a"})

# KPI Cards
def kpi_card(label, value, sub, color_class, icon):
    return dbc.Card([
        html.Div(icon, style={"position": "absolute", "right": "16px", "top": "16px", "fontSize": "28px", "opacity": "0.15"}),
        html.Div(label, className="text-muted text-uppercase small"),
        html.Div(value, className=f"kpi-value {color_class}"),
        html.Div(sub, className="text-muted small"),
    ], className="kpi-card", style={"height": "100%"})

kpi_row = dbc.Row([
    dbc.Col(kpi_card("Active Lines", "14", "Production lines running", "text-info", "🏭"), width=3),
    dbc.Col(kpi_card("Active Orders", "42", "Orders in pipeline", "text-success", "📦"), width=3),
    dbc.Col(kpi_card("Avg Efficiency", "72.4%", "Target: 75%", "text-warning", "⚡"), width=3),
    dbc.Col(kpi_card("Total Plan Qty", "1.8L", "Units this month", "text-danger", "⏰"), width=3),
], className="mb-4")

# Main Layout
app.layout = html.Div([
    sidebar,
    html.Div([
        # Dashboard Page
        html.Div(id="page-dashboard", children=[
            html.Div([
                html.H1("📊 Production Dashboard", style={"fontFamily": "Rajdhani", "fontSize": "28px", "fontWeight": "700"}),
                html.Span([html.Span(className="live-dot", style={"background": "#00e5a0", "animation": "pulse 1.5s infinite"}), "Live · Apr 2026"],
                          className="badge", style={"background": "rgba(0,198,255,0.1)", "border": "1px solid rgba(0,198,255,0.3)", "color": "#00c6ff", "padding": "4px 12px", "borderRadius": "20px"})
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "28px"}),

            kpi_row,

            html.H4("Active Production Lines", className="section-title mb-3"),
            # Add your line cards here similarly using dbc.Card (you can copy the structure)

            html.H4("Order Status Tracker", className="section-title mt-4 mb-3"),
            _build_order_tracker(),

        ], style={"marginLeft": "240px", "padding": "28px", "display": "block"}),

        # PPC Planner Page (hidden by default)
        html.Div(id="page-ppc", style={"marginLeft": "240px", "padding": "28px", "display": "none"}, children=[
            html.H1("📋 PPC Planner"),
            dbc.Input(id="ppc-search", placeholder="Search order, customer...", type="text", className="mb-3"),
            dbc.Table.from_dataframe(ppc_data, striped=True, bordered=True, hover=True, id="ppc-table"),
            html.H4("AI Plan Maker", className="section-title mt-4 mb-3"),
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dbc.Button("Train AI Models", id="ai-train-btn", color="info", className="w-100")
                        ], md=3),
                        dbc.Col([
                            dbc.Alert("Model status: not trained in this session", id="ai-train-status", color="secondary", className="mb-0")
                        ], md=9),
                    ], className="g-2 mb-3"),
                    dbc.Row([
                        dbc.Col(dcc.Dropdown(id="ai-customer", placeholder="Select Customer", options=[{"label": v, "value": v} for v in ENCODER_CACHE["Cstmr"]] or [{"label": "Train models first", "value": ""}]), md=4),
                        dbc.Col(dcc.Dropdown(id="ai-style", placeholder="Select Style", options=[{"label": v, "value": v} for v in ENCODER_CACHE["Style"]] or [{"label": "Train models first", "value": ""}]), md=4),
                        dbc.Col(dcc.Dropdown(id="ai-product", placeholder="Select Product", options=[{"label": v, "value": v} for v in ENCODER_CACHE["Product"]] or [{"label": "Train models first", "value": ""}]), md=4),
                    ], className="g-2 mb-2"),
                    dbc.Row([
                        dbc.Col(dbc.Input(id="ai-sam", placeholder="SAM", type="number"), md=3),
                        dbc.Col(dbc.Input(id="ai-plan-qty", placeholder="Plan Qty", type="number"), md=3),
                        dbc.Col(dbc.Button("Make Plan", id="ai-predict-btn", color="success", className="w-100"), md=2),
                        dbc.Col(dbc.Alert("Enter inputs and click Make Plan", id="ai-predict-output", color="dark", className="mb-0"), md=4),
                    ], className="g-2"),
                ])
            ], className="kpi-card"),
            html.H4("Predicted Plan Results", className="section-title mt-4 mb-3"),
            html.Div(id="prediction-results-container", children=[
                dbc.Alert("No predictions yet. Click 'Make Plan' to generate.", color="secondary")
            ])
        ]),

        # IE Planner Page
        html.Div(id="page-ie", style={"marginLeft": "240px", "padding": "28px", "display": "none"}, children=[
            html.H1("⚙️ IE Planner"),
            # Add IE cards, efficiency meter (use dcc.Graph with bar chart), and table
        ]),

    ], style={"marginLeft": "220px"})
])

# ================== CALLBACKS ==================
@callback(
    [Output("page-dashboard", "style"),
     Output("page-ppc", "style"),
     Output("page-ie", "style")],
    [Input("nav-dashboard", "n_clicks"),
     Input("nav-ppc", "n_clicks"),
     Input("nav-ie", "n_clicks")]
)
def switch_page(_, __, ___):
    ctx = dash.callback_context
    if not ctx.triggered:
        return {"display": "block"}, {"display": "none"}, {"display": "none"}

    trigger = ctx.triggered[0]["prop_id"].split(".")[0]

    if trigger == "nav-dashboard":
        return {"display": "block"}, {"display": "none"}, {"display": "none"}
    elif trigger == "nav-ppc":
        return {"display": "none"}, {"display": "block"}, {"display": "none"}
    elif trigger == "nav-ie":
        return {"display": "none"}, {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}, {"display": "none"}


@callback(
    [
        Output("ai-train-status", "children"),
        Output("ai-train-status", "color"),
        Output("ai-customer", "options"),
        Output("ai-style", "options"),
        Output("ai-product", "options"),
    ],
    Input("ai-train-btn", "n_clicks"),
    prevent_initial_call=True,
)
def train_models_callback(_):
    try:
        stats = train_ai_models(EXCEL_PATH)
        _load_encoder_cache()  # Reload cache after training
        customer_opts = [{"label": v, "value": v} for v in ENCODER_CACHE["Cstmr"]]
        style_opts = [{"label": v, "value": v} for v in ENCODER_CACHE["Style"]]
        product_opts = [{"label": v, "value": v} for v in ENCODER_CACHE["Product"]]
        return (
            f"✅ Training complete: {stats['rows']} rows, {stats['classes']} line classes.",
            "success",
            customer_opts,
            style_opts,
            product_opts,
        )
    except Exception as exc:
        return f"❌ Training failed: {exc}", "danger", [], [], []


@callback(
    [
        Output("ai-predict-output", "children"),
        Output("ai-predict-output", "color"),
        Output("prediction-results-container", "children"),
    ],
    Input("ai-predict-btn", "n_clicks"),
    [
        State("ai-customer", "value"),
        State("ai-style", "value"),
        State("ai-product", "value"),
        State("ai-sam", "value"),
        State("ai-plan-qty", "value"),
    ],
    prevent_initial_call=True,
)
def predict_plan_callback(_, customer, style, product, sam, plan_qty):
    try:
        if not all([customer, style, product]) or sam is None or plan_qty is None:
            return "Please enter Customer, Style, Product, SAM, and Plan Qty.", "warning", dbc.Alert("Missing inputs.", color="warning")

        model_line, model_days, encoders = _load_artifacts()
        row = {
            "Cstmr": _encode_value(encoders["Cstmr"], customer, "customer"),
            "Style": _encode_value(encoders["Style"], style, "style"),
            "Product": _encode_value(encoders["Product"], product, "product"),
            "SAM": float(sam),
            "Plan Qty": float(plan_qty),
        }

        X_pred = pd.DataFrame([row], columns=FEATURES)
        line_encoded = int(model_line.predict(X_pred)[0])
        pred_line = encoders["Line #"].inverse_transform([line_encoded])[0]
        pred_days = max(1, int(round(float(model_days.predict(X_pred)[0]))))
        pred_end_date = (datetime.now() + timedelta(days=pred_days)).strftime("%d-%b-%Y")

        # Build prediction row with formulas
        pred_row = _build_prediction_row(
            customer=customer,
            style=style,
            product=product,
            sam=float(sam),
            plan_qty=float(plan_qty),
            pred_line=pred_line,
            pred_days=pred_days,
        )

        # Add to results (keep last 5 predictions)
        PREDICTION_RESULTS.insert(0, pred_row)
        if len(PREDICTION_RESULTS) > 5:
            PREDICTION_RESULTS.pop()

        # Create results table
        key_cols = [
            "Line #",
            "PO#",
            "Cstmr",
            "Style",
            "Product",
            "Plan Qty",
            "SAM",
            "Pln Eff %",
            "P.Dy Cpcty",
            "Ttl Stch",
            "Bal Sew",
            "Com Dys Wk",
            "Strt Sw Out Dt",
            "End Sew Date",
            "PPC Status",
        ]
        table_rows = []
        for pred_result in PREDICTION_RESULTS:
            table_rows.append(
                html.Tr(
                    [
                        html.Td(str(pred_result.get(col, ""))) for col in key_cols
                    ]
                )
            )

        results_table = dbc.Card(
            [
                dbc.CardBody(
                    [
                        html.Table(
                            [
                                html.Thead(
                                    html.Tr(
                                        [html.Th(col, style={"fontSize": "12px"}) for col in key_cols],
                                        style={"background": "#111827", "color": "#00c6ff"},
                                    )
                                ),
                                html.Tbody(table_rows),
                            ],
                            style={
                                "width": "100%",
                                "borderCollapse": "collapse",
                                "fontSize": "12px",
                            },
                        )
                    ]
                )
            ],
            className="kpi-card",
        )

        return (
            f"✅ Recommended Line: {pred_line} | Estimated Days: {pred_days} | Expected End: {pred_end_date}",
            "success",
            results_table,
        )
    except Exception as exc:
        return f"❌ Prediction failed: {exc}", "danger", dbc.Alert(f"Error: {exc}", color="danger")

# Add more callbacks for:
# - Order chip selection → stage tracker
# - Search filtering on PPC table
# - Modal opening on row click (use dbc.Modal)

if __name__ == "__main__":
    app.run(debug=True)