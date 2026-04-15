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
])

# ================== ORDER TRACKER HELPERS ==================
def build_stage_flow(order: dict) -> html.Div:
    """Build visual stage flow timeline with lead times."""
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


def build_order_tracker() -> html.Div:
    """Build complete order tracker component with all active orders."""
    order_cards = []
    
    for order in orders:
        current_stage = None
        for stage in order.get("stages", []):
            if stage.get("status") == "current":
                current_stage = stage
                break
        
        if not current_stage:
            for stage in order.get("stages", []):
                if stage.get("status") != "done":
                    current_stage = stage
                    break
        
        status_color = "success" if order.get("ppcStatus") == "Completed" else "info"
        
        card = dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.Div([
                        html.Div(f"PO: {order['po']}", style={"fontWeight": "700", "color": "#00c6ff", "fontSize": "14px"}),
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


print("✅ Order tracker helper functions loaded")
