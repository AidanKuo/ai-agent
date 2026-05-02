"""
dash_app.py — JARVIS Command Center (Dash)

Run with:
    python dash_app.py
"""

import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
import pandas as pd

from dash import (
    ALL, Dash, Input, Output, State, callback, clientside_callback, ctx,
    dcc, html, no_update,
)

from lib.constants import APPS_PATH, CONFIG_PATH
from lib.resume import generate_cover_letter, save_cover_letter_pdf, rewrite_sentence
from lib.company_researcher import research_company, ResearchContext
from utils.list_data import add_item, load_lists, remove_item
from utils.gateway import check_gateway_heartbeat, check_gateway_online, get_gateway_info

import yaml

# ── App init ──────────────────────────────────────────────────────────────────

cyto.load_extra_layouts()

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.CYBORG],
    title="JARVIS",
    suppress_callback_exceptions=True,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_apps_cache: list = []
_apps_mtime: float = 0.0

def _load_apps() -> list:
    global _apps_cache, _apps_mtime
    if not APPS_PATH.exists():
        return []
    try:
        mtime = APPS_PATH.stat().st_mtime
        if mtime != _apps_mtime:
            with open(APPS_PATH, encoding="utf-8") as f:
                _apps_cache = json.load(f)
            _apps_mtime = mtime
        return _apps_cache
    except Exception:
        return []


def _save_apps(apps: list) -> None:
    global _apps_cache, _apps_mtime
    with open(APPS_PATH, "w", encoding="utf-8") as f:
        json.dump(apps, f, indent=2)
    _apps_cache = apps
    _apps_mtime = APPS_PATH.stat().st_mtime


EXCEL_PATH = Path(__file__).parent / "data" / "applied_jobs.xlsx"

def _update_applied_xlsx(apps: list) -> None:
    applied = sorted(
        [j for j in apps if j.get("status") == "applied"],
        key=lambda j: j.get("applied_at") or "",
        reverse=False,
    )
    df = pd.DataFrame([{
        "Company":     j.get("company", ""),
        "Title":       j.get("title", ""),
        "URL":         j.get("job_url", ""),
        "Applied At":  (j.get("applied_at", "") or "")[:10],
        "Date Posted": j.get("date_posted", ""),
        "Location":    j.get("location", ""),
        "Score":       j.get("score"),
        "Site":        j.get("site", ""),
        "Salary Min":  j.get("salary_min", ""),
        "Salary Max":  j.get("salary_max", ""),
        "Remote":      j.get("is_remote", False),
    } for j in applied])
    with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Applied Jobs")


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


LOG_PATH = Path(__file__).parent / "logs" / "agent.log"

STEP_LABELS = {
    1: "Scraping",
    2: "Scoring",
}


def _parse_pipeline_progress() -> dict:
    """
    Parse the last pipeline run from logs/agent.log.
    Returns a dict with keys:
      started_at, current_step, scoring_done, scoring_total,
      complete, elapsed, new_jobs, is_running
    """
    result = {
        "started_at":    None,
        "current_step":  0,
        "scoring_done":  None,
        "scoring_total": None,
        "complete":      False,
        "elapsed":       None,
        "new_jobs":      None,
        "is_running":    False,
    }
    if not LOG_PATH.exists():
        return result

    # Seek to last ~500 KB to avoid reading the entire log
    try:
        size = LOG_PATH.stat().st_size
        offset = max(0, size - 1_500_000)
        with open(LOG_PATH, "rb") as raw:
            raw.seek(offset)
            chunk = raw.read()
        lines = chunk.decode("utf-8", errors="ignore").splitlines(keepends=True)
        # Drop the first (possibly partial) line when we seeked mid-file
        if offset > 0 and lines:
            lines = lines[1:]
    except Exception:
        return result

    # Find the LAST "Pipeline started" line — that's our current run
    start_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if "Pipeline started:" in lines[i]:
            start_idx = i
            break

    if start_idx is None:
        return result

    run_lines = lines[start_idx:]

    for line in run_lines:
        # Started timestamp
        if "Pipeline started:" in line and result["started_at"] is None:
            try:
                ts = line.split("Pipeline started:")[-1].strip()
                result["started_at"] = ts
            except Exception:
                pass

        # Steps
        if "STEP 1" in line:
            result["current_step"] = max(result["current_step"], 1)
        if "STEP 2" in line:
            result["current_step"] = max(result["current_step"], 2)

        # Scoring progress  e.g. "[280/1819] Scoring:"
        # Each job logs twice (two scorer passes), so track max total seen
        if "] Scoring:" in line:
            try:
                scoring_pos = line.index("] Scoring:")
                open_pos = line.rindex("[", 0, scoring_pos)
                bracket = line[open_pos + 1: scoring_pos]
                done, total = bracket.split("/")
                t = int(total.strip())
                d = int(done.strip())
                if result["scoring_total"] is None or t > result["scoring_total"]:
                    result["scoring_total"] = t
                # done count maps to whichever total is the max
                if t == result["scoring_total"]:
                    result["scoring_done"] = d
            except Exception:
                pass

        # Scraper done — "Scraper complete — 909 new jobs" or "Scrape complete — 909 new jobs found"
        if "Scraper complete" in line or "Scrape complete" in line:
            m = re.search(r"(\d+)\s+new jobs", line)
            if m:
                result["new_jobs"] = int(m.group(1))

        # Pipeline complete
        if "Pipeline complete in" in line:
            result["complete"] = True
            try:
                result["elapsed"] = int(line.split("Pipeline complete in")[1].split("s")[0].strip())
            except Exception:
                pass

    # Running = started but not complete
    result["is_running"] = not result["complete"]
    return result



STATUS_COLORS = {
    "applied":        "#1d9e75",
    "ready_to_apply": "#17a2b8",
    "auto_apply":     "#2a7ab5",
    "needs_review":   "#ef9f27",
    "skipped":        "#3a5a72",
    "rejected":       "#e06060",
    "scraped":        "#3a5a72",
}

STATUS_LABELS = {
    "needs_review":   "Needs Review",
    "auto_apply":     "Auto-Apply",
    "ready_to_apply": "Ready to Apply",
    "applied":        "Applied",
    "skipped":        "Skipped",
    "rejected":       "Rejected",
    "scraped":        "Scraped",
}

# ── Shared card builders ──────────────────────────────────────────────────────

def _card(label, value, value_class, sub_lines):
    subs = [html.Div(s, style={"lineHeight": "1.7"}) for s in sub_lines]
    return html.Div([
        html.Div([html.Span(label)], className="card-label"),
        html.Div(value, className=f"card-value {value_class}"),
        html.Div(subs, className="card-sub"),
    ], className="jarvis-card")


def _info_row(key, val, val_class=""):
    return html.Div([
        html.Span(key, className="info-key"),
        html.Span(val, className=f"info-val {val_class}"),
    ], className="info-row")


def _stat_chip(label, value, sub=""):
    return html.Div([
        html.Div(label, style={"fontSize": "10px", "color": "#4a6a82",
                               "textTransform": "uppercase", "letterSpacing": "0.06em"}),
        html.Div(str(value), style={"fontSize": "22px", "fontWeight": "700",
                                    "color": "#c8dce8", "lineHeight": "1.2"}),
        html.Div(sub, style={"fontSize": "10px", "color": "#4a6a82"}),
    ], style={
        "background": "#0a1a28", "border": "0.5px solid #1a3040",
        "borderRadius": "8px", "padding": "10px 16px", "minWidth": "110px",
    })


# ── Dashboard tab layout ──────────────────────────────────────────────────────

def _dashboard_tab():
    return html.Div([
        # Health cards
        dbc.Row([
            dbc.Col(html.Div(id="card-gateway"), width=4),
            dbc.Col(html.Div(id="card-model"),   width=4),
            dbc.Col(html.Div(id="card-discord"), width=4),
        ], className="g-3 mb-0"),

        # Topology
        html.Div([
            html.Div([
                html.Div("System Topology", className="topology-title", style={"display": "inline-block"}),
                # Legend
                html.Div([
                    html.Span([html.Span(className="legend-dot", style={"background": "#1d9e75"}), "Online / OK"]),
                    html.Span([html.Span(className="legend-dot", style={"background": "#e06060"}), "Offline / Error"]),
                    html.Span([html.Span(className="legend-dot", style={"background": "#2a7ab5"}), "Connected"]),
                    html.Span([html.Span(className="legend-dot", style={"background": "#ef9f27"}), "Pending"]),
                    html.Span([html.Span(className="legend-dot", style={"background": "#1a3040"}), "Disabled"]),
                ], className="topology-legend"),
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "0.5rem"}),
            cyto.Cytoscape(
                id="topology",
                layout={"name": "preset"},
                style={"width": "100%", "height": "clamp(200px, 20vh, 300px)"},
                elements=[],
                stylesheet=[
                    # All nodes: pill shape, icon + name label inside
                    {
                        "selector": "node",
                        "style": {
                            "label":                "data(name)",
                            "text-valign":          "center",
                            "text-halign":          "center",
                            "color":                "data(color)",
                            "font-size":            "10.5px",
                            "font-weight":          "600",
                            "text-max-width":       "140px",
                            "background-color":     "#070f18",
                            "border-width":         "1.5px",
                            "border-color":         "data(color)",
                            "shape":                "round-rectangle",
                            "width":                "114px",
                            "height":               "36px",
                            "shadow-blur":          "16px",
                            "shadow-color":         "data(color)",
                            "shadow-opacity":       0.28,
                            "shadow-offset-x":      "0px",
                            "shadow-offset-y":      "0px",
                            "overlay-opacity":      0,
                        },
                    },
                    # Main Agent: slightly larger
                    {
                        "selector": "#agent-main",
                        "style": {
                            "width":        "122px",
                            "height":       "40px",
                            "font-size":    "11px",
                            "border-width": "2px",
                        },
                    },
                    # Edges
                    {
                        "selector": "edge",
                        "style": {
                            "label":                    "data(label)",
                            "font-size":                "9px",
                            "font-weight":              "500",
                            "color":                    "#5a8aaa",
                            "text-background-color":    "#07111c",
                            "text-background-opacity":  1,
                            "text-background-padding":  "3px",
                            "line-color":               "#1e3a52",
                            "width":                    "1.5px",
                            "curve-style":              "bezier",
                            "target-arrow-color":       "#2a5a7a",
                            "target-arrow-shape":       "triangle",
                            "arrow-scale":              0.9,
                            "overlay-opacity":          0,
                        },
                    },
                ],
            ),
            html.Div(id="topology-labels"),
        ], className="topology-panel"),

        html.Div(id="dashboard-stats", className="mt-3"),

    ])


# ── Pipeline tab layout ───────────────────────────────────────────────────────

# Group filter dropdown options — derived from config at startup
def _build_group_options() -> list[dict]:
    cfg    = _load_config()
    groups = cfg.get("scraper", {}).get("search_groups", [])
    opts   = [{"label": "All Groups", "value": "all"}]
    labels = {"primary": "Primary", "it_support": "IT Support", "pre_actuary_houston": "Pre-Actuary (Houston)"}
    for g in groups:
        name = g.get("name", "")
        if name:
            opts.append({"label": labels.get(name, name.replace("_", " ").title()), "value": name})
    return opts

GROUP_OPTIONS = _build_group_options()

# Primary action filters — shown as full buttons in the filter bar
ACTION_FILTERS = [
    ("auto_apply", "Auto-Apply"),
    ("applied",    "Applied"),
]

# Secondary filters — shown as stat chips in the stats strip
STAT_FILTERS = [
    ("all", "All"),
]

# Combined — used by filter callbacks
FILTERS = ACTION_FILTERS + STAT_FILTERS


def _pipeline_tab():
    _divider = html.Span(style={
        "display": "inline-block", "width": "1px", "height": "16px",
        "background": "#1a3040", "verticalAlign": "middle", "margin": "0 8px",
    })

    _default_filter = "auto_apply"
    action_btns = [
        dbc.Button(
            [label, html.Span("0", id={"type": "filter-count", "index": status},
                               className="filter-count-badge")],
            id={"type": "filter-btn", "index": status},
            size="sm",
            className="me-1 mb-1 filter-active" if status == _default_filter else "me-1 mb-1",
            color="secondary", outline=True,
        )
        for status, label in ACTION_FILTERS
    ]
    stat_chips = [
        html.Span(
            [label, " ",
             html.Span("0", id={"type": "filter-count", "index": status},
                       style={"fontWeight": "600", "color": "#6a8aaa"})],
            id={"type": "filter-btn", "index": status},
            n_clicks=0,
            className="stat-chip filter-active" if status == _default_filter else "stat-chip",
            style={"cursor": "pointer"},
        )
        for status, label in STAT_FILTERS
    ]
    return html.Div([
        # Pipeline progress banner
        html.Div(id="panel-pipeline-progress", className="mb-2"),

        # Row 1: primary action filters
        html.Div([
            *action_btns,
            _divider,
            *stat_chips,
            # Bulk actions — only visible on needs_review
            html.Div([
                _divider,
                dbc.Button("✓ Accept All", id="btn-accept-all", size="sm",
                           color="success", outline=True, className="me-1"),
                dbc.Button("✕ Reject All", id="btn-reject-all", size="sm",
                           color="danger", outline=True),
                html.Span(id="bulk-action-feedback",
                          style={"fontSize": "11px", "color": "#6a8aaa", "marginLeft": "8px"}),
            ], id="bulk-action-bar", style={"display": "none", "alignItems": "center"}),
        ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap",
                  "marginBottom": "6px"}),

        # Row 2: group filter + refresh
        html.Div([
            html.Div(style={"flex": "1"}),
            dcc.Dropdown(
                id="group-filter-dropdown",
                options=GROUP_OPTIONS,
                value="all",
                clearable=False,
                style={"width": "190px", "fontSize": "12px"},
            ),
            dbc.Button("↺", id="btn-refresh-jobs", size="sm",
                       color="secondary", outline=True,
                       title="Reload jobs from disk",
                       style={"fontSize": "13px", "padding": "2px 10px"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px",
                  "marginBottom": "12px"}),

        # Two-column: job list | detail panel
        dbc.Row([
            # Job list
            dbc.Col([
                dcc.Loading(type="dot", color="#2a7ab5", children=[
                    html.Div(id="job-list", style={
                        "height": "calc(100vh - 260px)",
                        "minHeight": "400px",
                        "overflowY": "auto",
                        "paddingRight": "4px",
                    }),
                ]),
            ], width=5),

            # Detail panel
            dbc.Col([
                dcc.Loading(type="dot", color="#2a7ab5", children=[
                    html.Div(id="job-detail", style={
                        "height": "calc(100vh - 260px)",
                        "minHeight": "400px",
                        "overflowY": "auto",
                    }),
                ]),
            ], width=7),
        ], className="g-3"),
    ])


# ── Masterlist tab layout ─────────────────────────────────────────────────────

LIST_META = [
    ("buy",   "Buy"),
    ("todo",  "Todo"),
    ("watch", "Watch"),
]


def _list_column(list_name, label):
    return dbc.Col([
        html.Div([
            html.Div(label, className="info-panel-title"),
            html.Div(id=f"{list_name}-display", style={
                "minHeight": "200px", "maxHeight": "400px", "overflowY": "auto",
                "marginBottom": "12px",
            }),
            dbc.Input(
                id=f"{list_name}-input",
                placeholder=f"Add to {label}…",
                size="sm",
                style={"fontSize": "12px"},
                className="mb-2",
            ),
            dbc.Button("Add", id=f"{list_name}-add-btn",
                       size="sm", color="primary", outline=True, className="w-100"),
        ], className="info-panel", style={"height": "100%"}),
    ], width=4)


def _masterlist_tab():
    return html.Div([
        dbc.Row(
            [_list_column(name, label) for name, label in LIST_META],
            className="g-3",
        ),
    ])


def _render_items(list_name, items):
    if not items:
        return html.Div("Nothing here yet.",
                        style={"fontSize": "12px", "color": "#3a5a72", "padding": "8px 0"})
    return html.Div([
        html.Div([
            html.Span(item["text"], style={"fontSize": "13px", "color": "#e0ecf4", "flex": "1"}),
            dbc.Button("✕",
                       id={"type": "remove-btn", "index": f"{list_name}:{item['id']}"},
                       size="sm", color="danger", outline=True,
                       style={"fontSize": "10px", "padding": "1px 6px", "lineHeight": "1"}),
        ], style={
            "display": "flex", "alignItems": "center", "justifyContent": "space-between",
            "padding": "6px 4px", "borderBottom": "0.5px solid #1a3040",
        })
        for item in items
    ])


# ── Sidebar nav pages ─────────────────────────────────────────────────────────

PAGES = [
    ("dashboard",  "Dashboard",    "▣"),
    ("pipeline",   "Job Pipeline", "◈"),
    ("masterlist", "Masterlist",   "≡"),
]


# ── Fish tank ─────────────────────────────────────────────────────────────────

def _svg_uri(svg: str) -> str:
    """Encode an SVG string as a data URI for use in html.Img src."""
    import urllib.parse
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def _fish_svg(color: str) -> str:
    return (
        f'<svg viewBox="0 0 22 12" width="22" height="12" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M0,2 L5,6 L0,10" stroke="{color}" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<ellipse cx="13" cy="6" rx="8.5" ry="4.5" stroke="{color}" stroke-width="1.5" fill="none"/>'
        f'<path d="M10,1.5 L13,0 L16,1.5" stroke="{color}" stroke-width="1.3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="19" cy="5.5" r="1.2" fill="{color}"/>'
        f'</svg>'
    )


def _seaweed_svg(h: int) -> str:
    h2, h3 = h * 2 // 3, h // 3
    return (
        f'<svg viewBox="0 0 10 {h}" width="10" height="{h}" xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M5,{h} C0,{h2} 10,{h3} 5,0" stroke="#1d7a50" stroke-width="2.5" fill="none" stroke-linecap="round"/>'
        f'<path d="M5,{h} C10,{h2} 0,{h3} 5,0" stroke="#145838" stroke-width="1.2" fill="none" stroke-linecap="round" opacity="0.6"/>'
        f'</svg>'
    )


def _fish_bg() -> list:
    """Returns a list of absolutely-positioned fish tank background elements
    sized for the 196px sidebar. Intended to be spread into the sidebar div."""
    fish_defs = [
        ("#e07828", "11%",  "r", "8s",   "0s",    "0s"),
        ("#4a9fd4", "29%",  "l", "13s",  "-5s",   "-0.9s"),
        ("#c84040", "47%",  "r", "10s",  "-3s",   "-0.4s"),
        ("#d4a020", "63%",  "l", "16s",  "-8s",   "-1.3s"),
        ("#9050c0", "78%",  "r", "11s",  "-6s",   "-0.6s"),
    ]

    fish_els = []
    for color, top, direction, dur, delay, bob_d in fish_defs:
        img = html.Img(src=_svg_uri(_fish_svg(color)), width=22, height=12,
                       style={"display": "block"})
        fish_inner = html.Div(img, className="fish-y",
                              style={"animationDelay": bob_d})
        fish_outer = html.Div(fish_inner,
                              className="fish-x swim-right" if direction == "r" else "fish-x swim-left",
                              style={"top": top, "animationDuration": dur, "animationDelay": delay})
        fish_els.append(fish_outer)

    # Seaweed — spread across 196px
    sw_specs = [(20, 48, "0s"), (90, 36, "-1.4s"), (155, 42, "-0.7s")]
    seaweed_els = [
        html.Div(
            html.Img(src=_svg_uri(_seaweed_svg(h)), width=10, height=h,
                     style={"display": "block"}),
            className="seaweed",
            style={"left": f"{x}px", "animationDelay": sd},
        )
        for x, h, sd in sw_specs
    ]

    # Bubbles — spread across 196px
    bubble_specs = [
        ("18px",  "4px", "4.5s", "0s"),
        ("70px",  "3px", "6.2s", "-2s"),
        ("130px", "5px", "5.1s", "-4s"),
        ("50px",  "3px", "7.3s", "-1s"),
        ("170px", "4px", "4.8s", "-3s"),
        ("100px", "3px", "8.4s", "-5.5s"),
    ]
    bubble_els = [
        html.Div(className="bubble", style={
            "left": lft, "width": sz, "height": sz,
            "animationDuration": dur, "animationDelay": dly,
        })
        for lft, sz, dur, dly in bubble_specs
    ]

    return fish_els + seaweed_els + bubble_els + [html.Div(className="fish-tank-gravel")]


# ── Root layout ───────────────────────────────────────────────────────────────

app.layout = html.Div([
    # Sidebar (fish tank background + nav overlay)
    html.Div([
        # Fish tank background (absolutely positioned, z-index 0)
        *_fish_bg(),

        # Brand
        html.Div([
            html.Div("JARVIS", className="jarvis-title"),
            html.Div("OpenClaw", className="jarvis-subtitle"),
        ], className="sidebar-brand"),

        # Nav
        html.Div([
            html.Div([
                html.Span(icon, className="nav-icon"),
                html.Span(label),
            ], id={"type": "nav-item", "index": page_id},
               className="nav-item active" if page_id == "pipeline" else "nav-item",
               n_clicks=0)
            for page_id, label, icon in PAGES
        ], className="sidebar-nav"),

        # Footer: status
        html.Div(id="header-status", className="sidebar-footer"),
    ], className="sidebar"),

    # Main content
    html.Div([
        html.Div(_dashboard_tab(),   id="page-dashboard",  style={"display": "none"}),
        html.Div(_pipeline_tab(),    id="page-pipeline",   style={"display": "block"}),
        html.Div(_masterlist_tab(),  id="page-masterlist", style={"display": "none"}),

        # All stores
        dcc.Store(id="selected-job-id",    data=None),
        dcc.Store(id="status-filter",      data="auto_apply"),
        dcc.Store(id="group-filter",       data="all"),
        dcc.Store(id="job-list-version",   data=0),
        dcc.Store(id="ats-result",         data=None),
        dcc.Store(id="cover-letter-text",      data=None),
        dcc.Store(id="research-data",          data=None),
        dcc.Store(id="cl-selected-sentence",   data=None),
        dcc.Store(id="list-refresh-trigger", data=0),
        dcc.Store(id="list-action",          data=None),
        dcc.Store(id="remove-item-store",    data=None),
        dcc.Store(id="active-page",          data="pipeline"),
        dcc.Store(id="_highlight-sink",      data=None),
        dcc.Store(id="toast-trigger",        data=None),

        dcc.Interval(id="tick", interval=30_000, n_intervals=0),

        # Toast notification container
        html.Div(id="toast-container", style={
            "position": "fixed", "bottom": "24px", "right": "24px", "zIndex": "9999",
            "minWidth": "260px",
        }),
    ], className="main-content"),
], className="app-shell")


# ── Sidebar: navigate ────────────────────────────────────────────────────────

@callback(
    Output("active-page", "data"),
    Input({"type": "nav-item", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def navigate(n_clicks):
    triggered = ctx.triggered_id
    if triggered and isinstance(triggered, dict):
        return triggered["index"]
    return no_update


@callback(
    Output({"type": "nav-item", "index": ALL}, "className"),
    Output("page-dashboard",  "style"),
    Output("page-pipeline",   "style"),
    Output("page-masterlist", "style"),
    Input("active-page", "data"),
)
def render_nav(active):
    page_ids = [p[0] for p in PAGES]
    nav_classes = [
        "nav-item active" if pid == active else "nav-item"
        for pid in page_ids
    ]
    styles = [
        {"display": "block"} if pid == active else {"display": "none"}
        for pid in page_ids
    ]
    return nav_classes, *styles


# ── Topology elements ─────────────────────────────────────────────────────────

def _build_elements(online, gw, hb):
    gw_color   = "#1d9e75" if online else "#e06060"
    disc_color = "#2a7ab5" if gw["discord_enabled"] else "#3a5a72"
    hb_color   = "#1d9e75" if hb.get("ok") else "#e06060"
    hb_str     = f"{hb['latency_ms']}ms" if hb.get("latency_ms") is not None else "—"

    return [
        # Nodes
        {"data": {"id": "heartbeat",  "name": f"◉  Heartbeat  {hb_str}", "color": hb_color},   "position": {"x": 85,  "y": 120}},
        {"data": {"id": "gateway",    "name": "⬡  Gateway",               "color": gw_color},   "position": {"x": 260, "y": 120}},
        {"data": {"id": "agent-main", "name": "◈  Main Agent",            "color": "#2a7ab5"},  "position": {"x": 455, "y": 120}},
        {"data": {"id": "discord",    "name": "◎  Discord",               "color": disc_color}, "position": {"x": 615, "y": 48}},
        # Edges
        {"data": {"source": "heartbeat",  "target": "gateway",    "label": "check"}},
        {"data": {"source": "gateway",    "target": "agent-main", "label": "API"}},
        {"data": {"source": "agent-main", "target": "discord",    "label": "notify"}},
    ]


# ── Dashboard callback ────────────────────────────────────────────────────────

@callback(
    Output("header-status",           "children"),
    Output("card-gateway",            "children"),
    Output("card-model",              "children"),
    Output("card-discord",            "children"),
    Output("topology",                "elements"),
    Output("topology-labels",         "children"),
    Output("panel-pipeline-progress", "children"),
    Output("dashboard-stats",         "children"),
    Input("tick", "n_intervals"),
)
def refresh_dashboard(_n):
    gw     = get_gateway_info()
    online = check_gateway_online(gw["port"])
    hb     = check_gateway_heartbeat(gw["port"])

    # Header
    dot_cls  = "online" if online else "offline"
    lbl_cls  = "" if online else "offline"
    lbl_text = f"Connected · {gw['port']}" if online else "Offline"
    header_status = html.Span([
        html.Span(className=f"status-dot {dot_cls}"),
        html.Span(lbl_text, className=f"status-label {lbl_cls}"),
    ])

    # Gateway card
    gw_card = _card(
        "Gateway",
        "Online" if online else "Offline",
        "card-online" if online else "card-offline",
        [f"port {gw['port']} / {gw['mode']}", f"v{gw['version']}"],
    )

    # Model card
    info      = gw["default_model_info"]
    reasoning = "on" if info.get("reasoning") else "off"
    host      = gw["ollama_url"].replace("http://", "")
    ctx_size   = f"{info.get('contextWindow', 0):,}" if info else "?"
    model_card = _card(
        "Model", gw["default_model_id"], "card-blue",
        [f"Ollama / {host}", f"reasoning: {reasoning} · ctx: {ctx_size}"],
    )

    # Discord card
    if gw["discord_enabled"]:
        discord_card = _card("Discord", "Connected", "card-online",
            [f"{gw['discord_guild_count']} guild", f"allowlist: {gw['discord_allowlist_count']} user"])
    else:
        discord_card = _card("Discord", "Off", "card-offline", ["Not configured"])

    # Topology
    elements = _build_elements(online, gw, hb)

    # Labels rendered inside Cytoscape nodes directly — overlay not needed
    node_labels = html.Div()

    # Pipeline progress banner (compact strip for Pipeline tab)
    prog = _parse_pipeline_progress()

    if prog["is_running"]:
        status_text  = "Running"
        status_color = "#ef9f27"
        dot_cls      = "status-dot online"
    elif prog["complete"]:
        status_text  = "Complete"
        status_color = "#1d9e75"
        dot_cls      = "status-dot online"
    elif prog["started_at"]:
        status_text  = "Idle"
        status_color = "#3a5a72"
        dot_cls      = "status-dot offline"
    else:
        status_text  = "No runs yet"
        status_color = "#3a5a72"
        dot_cls      = "status-dot offline"

    # Step indicator chips
    step_chips = []
    for s in range(1, len(STEP_LABELS) + 1):
        done    = s < prog["current_step"] or (s == prog["current_step"] and prog["complete"])
        active  = s == prog["current_step"] and prog["is_running"]
        pending = s > prog["current_step"]
        if done:
            chip_style = {"background": "#0d2a1e", "color": "#1d9e75",
                          "border": "1px solid #1d9e75"}
            prefix = "✓ "
        elif active:
            chip_style = {"background": "#2a1e00", "color": "#ef9f27",
                          "border": "1px solid #ef9f27"}
            prefix = "▶ "
        else:
            chip_style = {"background": "#0c1824", "color": "#3a5a72",
                          "border": "1px solid #1a3040"}
            prefix = ""

        lbl = STEP_LABELS[s]
        if s == 1 and prog["new_jobs"] is not None and not pending:
            lbl += f" · {prog['new_jobs']}"
        step_chips.append(
            html.Span(f"{prefix}{lbl}", style={
                "fontSize": "11px", "padding": "3px 9px", "borderRadius": "4px",
                "fontWeight": "500", **chip_style,
            })
        )

    # Scoring progress bar
    bar_section = []
    if prog["scoring_done"] is not None and prog["scoring_total"]:
        pct = min(100, int(prog["scoring_done"] / prog["scoring_total"] * 100))
        bar_section = [
            html.Div([
                html.Div(html.Div(style={
                    "height": "4px", "width": f"{pct}%",
                    "background": "#ef9f27", "borderRadius": "2px",
                    "transition": "width 0.5s ease",
                }), style={
                    "background": "#1a3040", "borderRadius": "2px",
                    "height": "4px", "minWidth": "120px", "maxWidth": "200px", "flex": "1",
                }),
            ], style={"display": "flex", "alignItems": "center"}),
            html.Span(f"{prog['scoring_done']}/{prog['scoring_total']} ({pct}%)", style={
                "fontSize": "11px", "color": "#ef9f27", "whiteSpace": "nowrap",
            }),
        ]

    meta_parts = []
    if prog["started_at"]:
        meta_parts.append(html.Span(f"Started {prog['started_at']}",
                                    style={"fontSize": "11px", "color": "#4a6a82"}))
    if prog["elapsed"]:
        meta_parts.append(html.Span(f"{prog['elapsed']}s",
                                    style={"fontSize": "11px", "color": "#4a6a82"}))

    pipeline_progress_panel = html.Div([
        html.Div([
            # Status pill
            html.Span([
                html.Span(className=dot_cls),
                html.Span(status_text, style={"fontSize": "11px", "color": status_color,
                                              "fontWeight": "600"}),
            ], style={"display": "flex", "alignItems": "center", "gap": "5px"}),
            # Divider
            html.Span(style={"width": "1px", "height": "16px",
                              "background": "#1a3040", "flexShrink": "0"}),
            # Step chips
            html.Div(step_chips, style={"display": "flex", "gap": "5px", "flexWrap": "wrap"}),
            # Scoring bar (only when active)
            *bar_section,
            # Meta (pushed to end)
            html.Div(meta_parts, style={"display": "flex", "gap": "12px",
                                         "marginLeft": "auto"}),
        ], style={
            "display": "flex", "alignItems": "center", "gap": "12px",
            "padding": "8px 14px",
            "background": "#0a1a28",
            "border": "0.5px solid #1a3040",
            "borderRadius": "8px",
            "flexWrap": "wrap",
        }),
    ])

    # Stats strip
    apps_data  = _load_apps()
    today_str  = datetime.utcnow().strftime("%Y-%m-%d")
    today_jobs = [j for j in apps_data if j.get("scraped_at", "").startswith(today_str)]

    score_dist = " · ".join(
        f"{s}★:{sum(1 for j in apps_data if j.get('score') == s)}"
        for s in (7, 8, 9, 10)
        if any(j.get("score") == s for j in apps_data)
    ) or "—"

    dashboard_stats = dbc.Row([
        dbc.Col(_stat_chip(
            "Auto-Apply Queue",
            sum(1 for j in apps_data if j.get("status") == "auto_apply"),
            "pending",
        ), width="auto"),
        dbc.Col(_stat_chip(
            "Applied (All Time)",
            sum(1 for j in apps_data if j.get("status") == "applied"),
        ), width="auto"),
        dbc.Col(_stat_chip(
            "Today Scraped",
            len(today_jobs),
            f"auto {sum(1 for j in today_jobs if j.get('status') == 'auto_apply')} · "
            f"rej {sum(1 for j in today_jobs if j.get('status') == 'rejected')}",
        ), width="auto"),
        dbc.Col(_stat_chip("Score Dist.", score_dist, "across all jobs"), width="auto"),
    ], className="g-2")

    return (header_status, gw_card, model_card, discord_card,
            elements, node_labels, pipeline_progress_panel, dashboard_stats)


# ── Pipeline: group filter ────────────────────────────────────────────────────

@callback(
    Output("group-filter", "data"),
    Input("group-filter-dropdown", "value"),
)
def update_group_filter(value):
    return value or "all"


# ── Pipeline: filter ──────────────────────────────────────────────────────────

@callback(
    Output("status-filter", "data"),
    Output({"type": "filter-btn", "index": ALL}, "className"),
    Input({"type": "filter-btn", "index": ALL}, "n_clicks"),
    State({"type": "filter-btn", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def update_filter(n_clicks, ids):
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update, no_update
    active      = triggered["index"]
    stat_ids    = {s for s, _ in STAT_FILTERS}
    classes = [
        ("stat-chip filter-active" if id_["index"] == active else "stat-chip")
        if id_["index"] in stat_ids else
        ("me-1 mb-1 filter-active" if id_["index"] == active else "me-1 mb-1")
        for id_ in ids
    ]
    return active, classes


# ── Pipeline: filter count badges ─────────────────────────────────────────────

@callback(
    Output({"type": "filter-count", "index": ALL}, "children"),
    Input("tick", "n_intervals"),
    State({"type": "filter-count", "index": ALL}, "id"),
)
def refresh_filter_counts(_n, ids):
    apps   = _load_apps()
    counts = {}
    for a in apps:
        s = a.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    counts["all"] = len(apps)
    return [str(counts.get(id_["index"], 0)) for id_ in ids]


# ── Pipeline: job list ────────────────────────────────────────────────────────

@callback(
    Output("job-list", "children"),
    Input("status-filter", "data"),
    Input("group-filter", "data"),
    Input("job-list-version", "data"),
)
def render_job_list(status_filter, group_filter, _version):
    all_apps = _load_apps()
    apps = all_apps
    if status_filter and status_filter != "all":
        apps = [a for a in apps if a.get("status") == status_filter]

    # Filter by search group when a specific group is selected
    if group_filter and group_filter != "all":
        apps = [a for a in apps if a.get("search_group") == group_filter]

    if status_filter == "auto_apply":
        # Show jobs scraped within the last 3 days
        latest_date = max(
            (a.get("scraped_at", "")[:10] for a in apps if a.get("scraped_at")),
            default="",
        )
        if latest_date:
            cutoff = (datetime.strptime(latest_date, "%Y-%m-%d") - timedelta(days=2)).strftime("%Y-%m-%d")
            apps = [a for a in apps if a.get("scraped_at", "")[:10] >= cutoff]

        # Suppress jobs whose title+company already has a skipped or applied record
        # (handles re-scraped duplicates with new IDs)
        handled = {
            (a.get("title", "").lower().strip(), a.get("company", "").lower().strip())
            for a in all_apps
            if a.get("status") in ("skipped", "applied")
        }
        apps = [
            a for a in apps
            if (a.get("title", "").lower().strip(), a.get("company", "").lower().strip())
            not in handled
        ]

        # Deduplicate by title+company, keeping highest score
        seen_keys: dict = {}
        for a in apps:
            key = (a.get("title", "").lower().strip(), a.get("company", "").lower().strip())
            if key not in seen_keys or (a.get("score") or 0) > (seen_keys[key].get("score") or 0):
                seen_keys[key] = a
        apps = list(seen_keys.values())
        # Two-pass stable sort: date desc first, then score desc
        apps = sorted(apps, key=lambda a: a.get("date_posted") or a.get("scraped_at", ""), reverse=True)
        apps = sorted(apps, key=lambda a: a.get("score") or 0, reverse=True)
    else:
        apps = sorted(apps, key=lambda a: a.get("date_posted") or a.get("scraped_at", ""), reverse=True)

    if not apps:
        return html.Div("No jobs in this category.", className="info-key",
                        style={"fontSize": "12px", "padding": "1rem"})

    total = len(apps)
    apps = apps[:200]

    items = []
    for job in apps:
        job_id = job["id"]
        score  = job.get("score")
        status = job.get("status", "")
        color  = STATUS_COLORS.get(status, "#3a5a72")

        score_text = f"{score}/10" if score is not None else "?"
        if score is None or score < 7:
            score_cls = "pill-red"
        elif score >= 8:
            score_cls = "pill-green"
        else:
            score_cls = "pill-amber"

        # Remote badge + salary
        meta_badges = []
        if job.get("is_remote"):
            meta_badges.append(html.Span("Remote", style={
                "fontSize": "10px", "color": "#1d9e75",
                "background": "rgba(29,158,117,0.12)",
                "padding": "1px 5px", "borderRadius": "3px", "marginLeft": "5px",
            }))
        def _parse_sal(v):
            try:
                f = float(v)
                return f if f == f and f > 0 else None  # NaN check: NaN != NaN
            except (TypeError, ValueError):
                return None
        sal_min = _parse_sal(job.get("salary_min"))
        sal_max = _parse_sal(job.get("salary_max"))
        if sal_min or sal_max:
            sal_str = (f"${int(sal_min/1000)}k" if sal_min else "?") + \
                      (f"–${int(sal_max/1000)}k" if sal_max else "+")
            meta_badges.append(html.Span(sal_str, style={
                "fontSize": "10px", "color": "#5a7a8a", "marginLeft": "5px",
            }))

        items.append(html.Div([
            html.Div([
                html.Div(job.get("title", "—"), style={
                    "fontSize": "13px", "fontWeight": "600",
                    "color": "#e0ecf4", "marginBottom": "2px",
                }),
                html.Div([
                    html.Span(
                        f"{job.get('company', '—')} · {job.get('location', '—')}",
                        style={"fontSize": "11px", "color": "#6a8a9e"},
                    ),
                    *meta_badges,
                ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap"}),
            ], style={"flex": "1"}),
            html.Span(score_text, className=f"metric-pill {score_cls}",
                      style={"fontSize": "10px", "padding": "2px 7px"}),
        ], id={"type": "job-item", "index": job_id}, className="job-item", style={
            "display": "flex", "alignItems": "center", "justifyContent": "space-between",
            "padding": "10px 12px", "marginBottom": "5px", "cursor": "pointer",
            "borderRadius": "8px",
            "background": "rgba(10,26,40,0.4)",
            "borderTop":    "0.5px solid #1a3040",
            "borderRight":  "0.5px solid #1a3040",
            "borderBottom": "0.5px solid #1a3040",
            "borderLeft":   f"3px solid {color}",
        }, n_clicks=0))

    if total > 200:
        items.append(html.Div(
            f"Showing 200 of {total} — apply or skip to see more",
            style={"fontSize": "11px", "color": "#4a6a82", "textAlign": "center", "padding": "8px"},
        ))

    return items


# ── Pipeline: select job ──────────────────────────────────────────────────────

@callback(
    Output("selected-job-id", "data"),
    Output("ats-result",       "data"),
    Output("cover-letter-text","data"),
    Output("research-data",    "data"),
    Input({"type": "job-item", "index": ALL}, "n_clicks"),
    State("selected-job-id", "data"),
    prevent_initial_call=True,
)
def select_job(n_clicks, current_id):
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update, no_update, no_update, no_update
    new_id = triggered["index"]
    if new_id == current_id:
        return no_update, no_update, no_update, no_update
    return new_id, None, None, None


# ── Pipeline: clientside selection highlight ──────────────────────────────────
# Updates CSS class on the clicked item without re-rendering the list.

clientside_callback(
    """
    function(selectedId) {
        document.querySelectorAll('.job-item').forEach(function(el) {
            el.classList.remove('job-item-selected');
        });
        if (selectedId) {
            document.querySelectorAll('.job-item').forEach(function(el) {
                try {
                    var id = JSON.parse(el.id);
                    if (id.index === selectedId) {
                        el.classList.add('job-item-selected');
                    }
                } catch(e) {}
            });
        }
        return null;
    }
    """,
    Output("_highlight-sink", "data"),
    Input("selected-job-id", "data"),
)


# ── Pipeline: detail panel ────────────────────────────────────────────────────

@callback(
    Output("job-detail", "children"),
    Input("selected-job-id",   "data"),
    Input("ats-result",        "data"),
    Input("cover-letter-text", "data"),
    Input("research-data",     "data"),
)
def render_detail(job_id, ats_result, cover_letter, research_data):
    if not job_id:
        return html.Div(
            html.Div("Select a job to view details.", style={
                "fontSize": "13px", "color": "#3a5a72",
            }),
            className="info-panel",
            style={"display": "flex", "alignItems": "center", "justifyContent": "center"},
        )

    apps = _load_apps()
    job  = next((a for a in apps if a["id"] == job_id), None)
    if not job:
        return html.Div("Job not found.", className="info-panel")

    status     = job.get("status", "")
    score      = job.get("score")
    color      = STATUS_COLORS.get(status, "#3a5a72")
    score_text = f"{score}/10" if score is not None else "?"
    if score is None or score < 7:
        score_cls = "pill-red"
    elif score >= 8:
        score_cls = "pill-green"
    else:
        score_cls = "pill-amber"

    # ── Info header (above tabs) ──────────────────────────────────────────────
    info_header = html.Div([
        html.Div(job.get("title", "—"), style={
            "fontSize": "16px", "fontWeight": "600", "color": "#e0ecf4", "marginBottom": "4px",
        }),
        html.Div(f"{job.get('company','—')} · {job.get('location','—')}",
                 style={"fontSize": "12px", "color": "#6a8a9e", "marginBottom": "8px"}),
        html.Div([
            html.Span(score_text, className=f"metric-pill {score_cls}"),
            html.Span(STATUS_LABELS.get(status, status), className="metric-pill",
                      style={"background": f"{color}22", "color": color, "fontSize": "10px"}),
            html.A("View Job →", href=job.get("job_url", "#"), target="_blank",
                   style={"fontSize": "11px", "color": "#5a8aaa", "marginLeft": "8px"}),
        ], className="mb-2"),
    ])

    # ── Actions (all statuses) ────────────────────────────────────────────────
    _input_style = {
        "fontSize": "11px", "background": "rgba(10,26,40,0.4)",
        "color": "#8ab0cc", "border": "0.5px solid #1a3040", "borderRadius": "6px",
    }
    has_eval = bool(job.get("career_ops_report") and Path(job["career_ops_report"]).exists())
    actions = html.Div([
        html.Div([
            dbc.Button("Mark Applied", id="btn-mark-applied", size="sm",
                       color="success", outline=True, className="me-2",
                       disabled=(status == "applied")),
            dbc.Button("Skip", id="btn-skip", size="sm",
                       color="secondary", outline=True, className="me-2",
                       disabled=(status == "skipped")),
            dcc.Loading(dbc.Button("ATS Scan", id="btn-ats-scan", size="sm",
                       color="secondary", outline=True, className="me-2"),
                       type="circle", color="#2a7ab5"),
            dbc.Button(
                "Full Eval ✓" if has_eval else "Full Eval",
                id="btn-full-eval", size="sm",
                color="info" if has_eval else "secondary",
                outline=True,
                disabled=not has_eval,
                title="Run 'evaluate job' in Claude Code to generate" if not has_eval else "Evaluation report available",
            ),
        ], className="mb-2"),
        html.Div([
            dcc.Dropdown(
                id="status-change-dropdown",
                options=[{"label": v, "value": k} for k, v in STATUS_LABELS.items()],
                value=status,
                clearable=False,
                style={"width": "165px", "fontSize": "11px", "flexShrink": "0"},
            ),
            dbc.Input(
                id="company-url-input",
                placeholder="Paste company URL (optional)",
                size="sm",
                style={**_input_style, "flex": "1", "minWidth": "0"},
            ),
            dcc.Loading(dbc.Button("Research", id="btn-cover-letter", size="sm",
                       color="secondary", outline=True, style={"flexShrink": "0"}),
                       type="circle", color="#2a7ab5"),
        ], style={"display": "flex", "alignItems": "center", "gap": "6px", "flexWrap": "wrap"}),
    ], className="mb-3")

    # ── Tab: Info — score reasoning (collapsible) ─────────────────────────────
    reasoning_content = html.Div(
        "No reasoning available.",
        style={"fontSize": "12px", "color": "#4a6a82", "padding": "8px 0"},
    )
    if job.get("reasoning"):
        reasoning_content = html.Div(job["reasoning"], style={
            "fontSize": "12px", "color": "#6a8a9e", "lineHeight": "1.7",
            "fontStyle": "italic", "borderLeft": "3px solid #1a3040",
            "paddingLeft": "10px", "paddingTop": "8px",
        })

    breakdown = job.get("score_breakdown", {})
    gaps      = job.get("gaps", [])
    archetype = job.get("archetype", "")
    info_tab = html.Details([
        html.Summary("Score Reasoning", className="detail-summary"),
        reasoning_content,
        html.Div([
            html.Span(f"Archetype: {archetype}", style={"marginRight": "12px"}),
            html.Span(f"Tech {breakdown.get('tech_match', '?')}/10", style={"marginRight": "12px"}),
            html.Span(f"Seniority {breakdown.get('seniority_fit', '?')}/10"),
        ], style={"fontSize": "11px", "color": "#4a6a82", "marginTop": "6px"}) if archetype else "",
        html.Div([
            html.Span("Gaps: ", style={"color": "#4a6a82"}),
            html.Span(", ".join(gaps) if isinstance(gaps, list) else str(gaps), style={"color": "#ef9f27"}),
        ], style={"fontSize": "11px", "marginTop": "4px"}) if gaps else "",
    ], style={"marginTop": "4px"})

    # ── Tab: Eval — career-ops evaluation report ──────────────────────────────
    report_path = job.get("career_ops_report")
    if report_path and Path(report_path).exists():
        report_md = Path(report_path).read_text(encoding="utf-8")
        eval_tab = html.Div([
            html.Div(
                f"Report: {Path(report_path).name}",
                style={"fontSize": "10px", "color": "#4a6a82", "marginBottom": "6px"},
            ),
            dcc.Markdown(
                report_md,
                style={
                    "fontSize": "11px", "color": "#8ab0cc", "lineHeight": "1.6",
                    "maxHeight": "480px", "overflowY": "auto",
                    "background": "rgba(10,26,40,0.4)", "borderRadius": "8px",
                    "padding": "0.75rem", "border": "0.5px solid #1a3040",
                },
            ),
            html.Div(
                f"Tailored resume: {job['tailored_resume']}" if job.get("tailored_resume") else "",
                style={"fontSize": "10px", "color": "#4a7a5a", "marginTop": "6px"},
            ),
        ])
    else:
        eval_tab = html.Div([
            html.Div("No evaluation report yet.", style={"fontSize": "12px", "color": "#4a6a82"}),
            html.Div(
                "Run 'evaluate job' in Claude Code to generate a full 7-block analysis, tailored resume PDF, and save the report here.",
                style={"fontSize": "11px", "color": "#3a5a72", "marginTop": "4px", "lineHeight": "1.5"},
            ),
        ], style={"padding": "8px 0"})

    # ── Tab: ATS ──────────────────────────────────────────────────────────────
    if not ats_result:
        ats_tab = html.Div("Run ATS Scan to see results.",
                           style={"fontSize": "12px", "color": "#4a6a82", "padding": "8px 0"})
    elif "error" in ats_result:
        ats_tab = html.Div(f"ATS scan error: {ats_result['error']}",
                           style={"color": "#e06060", "fontSize": "12px"})
    else:
        ats_score  = ats_result.get("ats_score", "?")
        missing    = ats_result.get("missing_keywords", [])
        present    = ats_result.get("present_keywords", [])
        wins       = ats_result.get("quick_wins", [])
        verdict    = ats_result.get("overall_verdict", "")
        weak       = ats_result.get("weak_bullets", [])
        skills     = ats_result.get("skills_issues", [])

        score_color = (
            "#5dcaa5" if isinstance(ats_score, (int, float)) and ats_score >= 70 else
            "#ef9f27" if isinstance(ats_score, (int, float)) and ats_score >= 50 else
            "#e06060"
        )
        _lbl = lambda t: html.Div(t, style={
            "fontSize": "11px", "color": "#4a6a82", "marginBottom": "4px", "marginTop": "8px",
            "textTransform": "uppercase", "letterSpacing": "0.05em",
        })
        present_str  = ", ".join(present[:12]) if present else ""
        missing_items = [
            html.Li([
                html.Span(k["keyword"], style={"color": "#c8dce8"}),
                html.Span(f" · {k.get('importance','?')}", style={"color": "#4a6a82"}),
                html.Span(f" — {k.get('where_to_add','')}", style={"color": "#6a8a9e", "fontStyle": "italic"}),
            ], style={"fontSize": "11px", "marginBottom": "3px"})
            for k in missing[:10]
        ]
        bullet_items = []
        for b in weak[:4]:
            if not isinstance(b, dict) or "original" not in b:
                continue
            bullet_items.append(html.Li([
                html.Div(f"Before: {b.get('original','')[:100]}", style={"color": "#e06060", "fontSize": "11px"}),
                html.Div(f"After:  {b.get('rewrite','')[:100]}", style={"color": "#5dcaa5", "fontSize": "11px"}),
                html.Div(b.get("issue", ""), style={"color": "#6a8a9e", "fontSize": "10px", "fontStyle": "italic"}),
            ], style={"marginBottom": "6px", "listStyle": "none", "paddingLeft": 0}))
        skills_items = [
            html.Li([
                html.Span(s.get("issue", ""), style={"color": "#ef9f27", "fontSize": "11px"}),
                html.Span(f" → {s.get('fix','')}", style={"color": "#6a8a9e", "fontSize": "11px"}),
            ], style={"marginBottom": "3px"})
            for s in skills[:5]
        ]
        win_items = [
            html.Li(w, style={"fontSize": "11px", "color": "#6a8a9e"}) for w in wins[:5]
        ]
        ats_tab = html.Div([
            html.Div([
                html.Span("ATS Score: ", className="info-key"),
                html.Span(f"{ats_score}/100", style={"color": score_color, "fontWeight": "700", "fontSize": "16px"}),
            ], className="mb-1"),
            html.Div(verdict, style={"fontSize": "12px", "color": "#8ab0cc", "marginBottom": "6px", "fontStyle": "italic"}),
            (_lbl("Present") if present_str else ""),
            html.Div(present_str, style={"fontSize": "11px", "color": "#5dcaa5", "marginBottom": "6px"}) if present_str else "",
            (_lbl("Missing Keywords") if missing else ""),
            html.Ul(missing_items, style={"paddingLeft": "16px", "marginBottom": "6px"}) if missing else "",
            (_lbl("Weak Bullets") if bullet_items else ""),
            html.Ul(bullet_items, style={"paddingLeft": 0, "marginBottom": "6px"}) if bullet_items else "",
            (_lbl("Skills Issues") if skills_items else ""),
            html.Ul(skills_items, style={"paddingLeft": "16px", "marginBottom": "6px"}) if skills_items else "",
            (_lbl("Quick Wins") if wins else ""),
            html.Ul(win_items, style={"paddingLeft": "16px"}) if wins else "",
        ])

    # ── Tab: Research ─────────────────────────────────────────────────────────
    if not research_data:
        research_tab = html.Div("Click Research to begin.",
                                style={"fontSize": "12px", "color": "#4a6a82", "padding": "8px 0"})
    else:
        rd = research_data
        _field_style = {
            "width": "100%", "fontSize": "11px", "color": "#8ab0cc",
            "background": "rgba(10,26,40,0.4)", "border": "0.5px solid #1a3040",
            "borderRadius": "6px", "padding": "0.5rem", "resize": "vertical", "marginBottom": "8px",
        }
        _q1_style  = {**_field_style, "border": "0.5px solid #a07830"}
        _lbl_std   = {"fontSize": "10px", "color": "#6a8a9e", "marginBottom": "3px"}
        _lbl_q1    = {"fontSize": "10px", "color": "#c89050", "marginBottom": "3px"}
        research_tab = html.Div([
            html.Div("Company-specific detail", style=_lbl_q1),
            dcc.Textarea(id="research-q1", value=rd.get("company_specific_detail", ""),
                         placeholder="Find one specific thing a lazy applicant wouldn't...",
                         style={**_q1_style, "height": "60px"}),
            html.Div("Why this role", style=_lbl_std),
            dcc.Textarea(id="research-q2", value=rd.get("why_this_role", ""),
                         style={**_field_style, "height": "48px"}),
            html.Div("Best matching project", style=_lbl_std),
            dcc.Textarea(id="research-q3", value=rd.get("best_project", ""),
                         style={**_field_style, "height": "48px"}),
            html.Div("Project-specific detail", style=_lbl_std),
            dcc.Textarea(id="research-q4", value=rd.get("project_detail", ""),
                         style={**_field_style, "height": "48px"}),
            html.Div("Matched requirements", style=_lbl_std),
            dcc.Textarea(id="research-q5", value=rd.get("matched_requirements", ""),
                         style={**_field_style, "height": "48px"}),
            html.Div("Take on company's work", style=_lbl_std),
            dcc.Textarea(id="research-q6", value=rd.get("company_take", ""),
                         style={**_field_style, "height": "48px"}),
            dcc.Loading(
                dbc.Button("Generate Letter", id="btn-generate-letter", size="sm",
                           color="primary", outline=True),
                type="circle", color="#2a7ab5",
            ),
        ])

    # ── Tab: Letter ───────────────────────────────────────────────────────────
    if not cover_letter:
        letter_tab = html.Div("Generate a letter after researching.",
                              style={"fontSize": "12px", "color": "#4a6a82", "padding": "8px 0"})
    else:
        cl_text = cover_letter.get("text", "") if isinstance(cover_letter, dict) else cover_letter
        cl_path = cover_letter.get("pdf_path") if isinstance(cover_letter, dict) else None
        sentences = re.split(r'(?<=[.!?])\s+', cl_text.strip()) if cl_text else []
        sentence_spans = [
            html.Span(
                s + (" " if i < len(sentences) - 1 else ""),
                id={"type": "cl-sentence", "index": i},
                className="cl-sentence",
                n_clicks=0,
            )
            for i, s in enumerate(sentences)
        ]
        letter_tab = html.Div([
            html.Div(
                sentence_spans,
                style={
                    "fontSize": "12px", "color": "#8ab0cc", "lineHeight": "1.8",
                    "whiteSpace": "pre-wrap", "background": "rgba(10,26,40,0.4)",
                    "border": "0.5px solid #1a3040", "borderRadius": "8px",
                    "padding": "1rem", "maxHeight": "340px", "overflowY": "auto",
                }
            ),
            html.Div("Click a sentence to edit or AI-rewrite it.",
                     style={"fontSize": "11px", "color": "#4a6a7a", "marginTop": "4px"}),
            html.Div(id="sentence-edit-panel"),
            html.Div(f"Saved: {cl_path}",
                     style={"fontSize": "11px", "color": "#4a7a5a", "marginTop": "6px"}) if cl_path else "",
        ])

    # ── Auto-advance to most recent tab ───────────────────────────────────────
    if cover_letter:
        default_tab = "tab-letter"
    elif research_data:
        default_tab = "tab-research"
    elif ats_result:
        default_tab = "tab-ats"
    elif has_eval:
        default_tab = "tab-eval"
    else:
        default_tab = "tab-info"

    return html.Div([
        info_header,
        actions,
        dbc.Tabs([
            dbc.Tab(info_tab,      label="Info",     tab_id="tab-info",
                    label_style={"fontSize": "11px"}, className="pt-2"),
            dbc.Tab(ats_tab,       label="ATS",      tab_id="tab-ats",
                    label_style={"fontSize": "11px"}, className="pt-2"),
            dbc.Tab(research_tab,  label="Research", tab_id="tab-research",
                    label_style={"fontSize": "11px"}, className="pt-2"),
            dbc.Tab(letter_tab,    label="Letter",   tab_id="tab-letter",
                    label_style={"fontSize": "11px"}, className="pt-2"),
            dbc.Tab(eval_tab,      label="Eval ✓" if has_eval else "Eval",
                    tab_id="tab-eval",
                    label_style={"fontSize": "11px", "color": "#5dcaa5" if has_eval else "#4a6a82"},
                    className="pt-2"),
        ], active_tab=default_tab, className="detail-tabs mt-1"),
    ], className="info-panel")


# ── Pipeline: mark applied ────────────────────────────────────────────────────

@callback(
    Output("selected-job-id",  "data", allow_duplicate=True),
    Output("job-list-version", "data", allow_duplicate=True),
    Output("toast-trigger",    "data", allow_duplicate=True),
    Input("btn-mark-applied",  "n_clicks"),
    State("selected-job-id",   "data"),
    State("job-list-version",  "data"),
    prevent_initial_call=True,
)
def mark_applied(n_clicks, job_id, version):
    if not n_clicks or not job_id:
        return no_update, no_update, no_update
    apps = _load_apps()
    for job in apps:
        if job["id"] == job_id:
            job["status"]     = "applied"
            job["applied_at"] = datetime.now().isoformat()
            break
    _save_apps(apps)
    threading.Thread(target=_update_applied_xlsx, args=(apps,), daemon=True).start()
    return None, (version or 0) + 1, {"message": "Marked as applied", "color": "success"}


# ── Pipeline: skip job ────────────────────────────────────────────────────────

@callback(
    Output("selected-job-id",  "data", allow_duplicate=True),
    Output("job-list-version", "data", allow_duplicate=True),
    Output("toast-trigger",    "data", allow_duplicate=True),
    Input("btn-skip",          "n_clicks"),
    State("selected-job-id",   "data"),
    State("job-list-version",  "data"),
    prevent_initial_call=True,
)
def skip_job(n_clicks, job_id, version):
    if not n_clicks or not job_id:
        return no_update, no_update, no_update
    apps = _load_apps()
    for job in apps:
        if job["id"] == job_id:
            job["status"] = "skipped"
            break
    _save_apps(apps)
    return None, (version or 0) + 1, {"message": "Job skipped", "color": "secondary"}


# ── Pipeline: bulk accept / reject ───────────────────────────────────────────

@callback(
    Output("bulk-action-bar", "style"),
    Input("status-filter", "data"),
)
def toggle_bulk_bar(status_filter):
    if status_filter == "needs_review":
        return {"display": "flex", "alignItems": "center"}
    return {"display": "none", "alignItems": "center"}


@callback(
    Output("status-filter",        "data", allow_duplicate=True),
    Output("bulk-action-feedback", "children", allow_duplicate=True),
    Output("toast-trigger",        "data", allow_duplicate=True),
    Input("btn-accept-all", "n_clicks"),
    State("status-filter", "data"),
    prevent_initial_call=True,
)
def accept_all(n_clicks, current_filter):
    if not n_clicks:
        return no_update, no_update, no_update
    apps = _load_apps()
    count = 0
    for job in apps:
        if job.get("status") == "needs_review":
            job["status"] = "auto_apply"
            count += 1
    _save_apps(apps)
    return "auto_apply", f"{count} accepted", {"message": f"{count} jobs accepted", "color": "success"}


@callback(
    Output("status-filter",        "data", allow_duplicate=True),
    Output("bulk-action-feedback", "children", allow_duplicate=True),
    Output("toast-trigger",        "data", allow_duplicate=True),
    Input("btn-reject-all", "n_clicks"),
    State("status-filter", "data"),
    prevent_initial_call=True,
)
def reject_all(n_clicks, current_filter):
    if not n_clicks:
        return no_update, no_update, no_update
    apps = _load_apps()
    count = 0
    for job in apps:
        if job.get("status") == "needs_review":
            job["status"] = "rejected"
            count += 1
    _save_apps(apps)
    return "rejected", f"{count} rejected", {"message": f"{count} jobs rejected", "color": "danger"}


# ── Toast notification ────────────────────────────────────────────────────────

@callback(
    Output("toast-container", "children"),
    Input("toast-trigger", "data"),
)
def show_toast(trigger):
    if not trigger:
        return []
    return dbc.Toast(
        trigger["message"],
        header="Done",
        is_open=True,
        dismissable=True,
        duration=3000,
        color=trigger.get("color", "success"),
        style={"fontSize": "12px", "minWidth": "220px"},
    )


# ── Pipeline: refresh job list ────────────────────────────────────────────────

@callback(
    Output("job-list-version", "data", allow_duplicate=True),
    Input("btn-refresh-jobs", "n_clicks"),
    State("job-list-version", "data"),
    prevent_initial_call=True,
)
def refresh_jobs(n_clicks, version):
    if not n_clicks:
        return no_update
    global _apps_mtime
    _apps_mtime = 0.0  # force cache invalidation on next load
    return (version or 0) + 1


# ── Pipeline: change job status via dropdown ──────────────────────────────────

@callback(
    Output("job-list-version", "data", allow_duplicate=True),
    Output("toast-trigger",    "data", allow_duplicate=True),
    Input("status-change-dropdown", "value"),
    State("selected-job-id",        "data"),
    State("job-list-version",       "data"),
    prevent_initial_call=True,
)
def change_status(new_status, job_id, version):
    if not new_status or not job_id:
        return no_update, no_update
    apps = _load_apps()
    old_status = None
    for job in apps:
        if job["id"] == job_id:
            old_status = job.get("status")
            if old_status == new_status:
                return no_update, no_update
            job["status"] = new_status
            break
    _save_apps(apps)
    label = STATUS_LABELS.get(new_status, new_status)
    return (version or 0) + 1, {"message": f"Status → {label}", "color": "primary"}


# ── Pipeline: ATS scan ────────────────────────────────────────────────────────

@callback(
    Output("ats-result", "data", allow_duplicate=True),
    Input("btn-ats-scan",    "n_clicks"),
    State("selected-job-id", "data"),
    prevent_initial_call=True,
)
def run_ats_scan(n_clicks, job_id):
    if not n_clicks or not job_id:
        return no_update
    apps = _load_apps()
    job  = next((a for a in apps if a["id"] == job_id), None)
    if not job:
        return {"error": "Job not found"}
    try:
        from agents.ats_scanner import scan_job
        return scan_job(job)
    except Exception as e:
        return {"error": str(e)}


# ── Pipeline: research (step 1) ───────────────────────────────────────────────

@callback(
    Output("research-data", "data", allow_duplicate=True),
    Input("btn-cover-letter",   "n_clicks"),
    State("selected-job-id",    "data"),
    State("company-url-input",  "value"),
    prevent_initial_call=True,
)
def run_research(n_clicks, job_id, company_url):
    if not n_clicks or not job_id:
        return no_update
    apps = _load_apps()
    job  = next((a for a in apps if a["id"] == job_id), None)
    if not job:
        return {}
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    from lib.resume import load_resume_text
    ctx = research_company(job, load_resume_text(), api_key, override_url=company_url or "")
    return ctx.to_dict()


# ── Pipeline: generate letter (step 2) ────────────────────────────────────────

@callback(
    Output("cover-letter-text", "data", allow_duplicate=True),
    Input("btn-generate-letter", "n_clicks"),
    State("research-q1",         "value"),
    State("research-q2",         "value"),
    State("research-q3",         "value"),
    State("research-q4",         "value"),
    State("research-q5",         "value"),
    State("research-q6",         "value"),
    State("selected-job-id",     "data"),
    prevent_initial_call=True,
)
def run_generate_letter(n_clicks, q1, q2, q3, q4, q5, q6, job_id):
    if not n_clicks or not job_id:
        return no_update
    apps = _load_apps()
    job  = next((a for a in apps if a["id"] == job_id), None)
    if not job:
        return {"text": "Job not found.", "pdf_path": None}
    labels = [
        ("Company-specific detail (use in opening)", q1),
        ("Why this role specifically",               q2),
        ("Best matching project from resume",        q3),
        ("Specific project detail to mention",       q4),
        ("Requirements candidate clearly has",       q5),
        ("Genuine take on company's work",           q6),
    ]
    research_block = "\n".join(
        f"{label}: {val}" for label, val in labels if val and val.strip()
    )
    try:
        cfg      = _load_config()
        text     = generate_cover_letter(job, cfg, research_block=research_block)
        pdf_path = save_cover_letter_pdf(text, job)
        return {"text": text, "pdf_path": pdf_path}
    except Exception as e:
        return {"text": f"Error generating cover letter: {e}", "pdf_path": None}


# ── Cover letter: sentence selection ─────────────────────────────────────────

@callback(
    Output("cl-selected-sentence", "data"),
    Input({"type": "cl-sentence", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_sentence(n_clicks_list):
    if not any(n_clicks_list):
        return no_update
    triggered = ctx.triggered_id
    if triggered and isinstance(triggered, dict):
        return triggered["index"]
    return no_update


@callback(
    Output("sentence-edit-panel", "children"),
    Input("cl-selected-sentence", "data"),
    State("cover-letter-text", "data"),
    prevent_initial_call=True,
)
def render_sentence_edit(idx, cover_letter):
    if idx is None or not cover_letter:
        return []
    cl_text = cover_letter.get("text", "") if isinstance(cover_letter, dict) else cover_letter
    import re as _re
    sentences = _re.split(r'(?<=[.!?])\s+', cl_text.strip())
    if idx >= len(sentences):
        return []
    sentence = sentences[idx]
    return html.Div([
        dcc.Textarea(
            id="sentence-edit-textarea",
            value=sentence,
            style={
                "width": "100%", "minHeight": "70px", "fontSize": "12px",
                "background": "rgba(10,26,40,0.6)", "color": "#8ab0cc",
                "border": "0.5px solid #2a5a7a", "borderRadius": "6px",
                "padding": "8px", "marginTop": "8px", "resize": "vertical",
            },
        ),
        html.Div([
            dbc.Button("AI Rewrite", id="btn-rewrite-sentence", size="sm",
                       color="primary", className="me-2 mt-2"),
            dbc.Button("Save Edit",  id="btn-save-sentence",    size="sm",
                       color="secondary", className="mt-2"),
        ]),
    ], style={"marginTop": "8px"})


@callback(
    Output("cover-letter-text", "data", allow_duplicate=True),
    Input("btn-rewrite-sentence", "n_clicks"),
    State("cl-selected-sentence",   "data"),
    State("sentence-edit-textarea", "value"),
    State("cover-letter-text",      "data"),
    State("selected-job-id",        "data"),
    prevent_initial_call=True,
)
def rewrite_sentence_cb(n_clicks, idx, sentence_text, cover_letter, job_id):
    if not n_clicks or idx is None or not cover_letter or not job_id:
        return no_update
    cl_text = cover_letter.get("text", "") if isinstance(cover_letter, dict) else cover_letter
    import re as _re
    sentences = _re.split(r'(?<=[.!?])\s+', cl_text.strip())
    if idx >= len(sentences):
        return no_update
    try:
        import os as _os
        cfg     = _load_config()
        api_key = _os.environ.get("ANTHROPIC_API_KEY", "")
        apps    = _load_apps()
        job     = next((a for a in apps if a["id"] == job_id), {})
        new_sentence = rewrite_sentence(sentence_text or sentences[idx], cl_text, job, api_key)
        sentences[idx] = new_sentence
        new_text = " ".join(sentences)
        pdf_path = save_cover_letter_pdf(new_text, job)
        return {"text": new_text, "pdf_path": pdf_path}
    except Exception as e:
        return no_update


@callback(
    Output("cover-letter-text", "data", allow_duplicate=True),
    Input("btn-save-sentence",      "n_clicks"),
    State("cl-selected-sentence",   "data"),
    State("sentence-edit-textarea", "value"),
    State("cover-letter-text",      "data"),
    State("selected-job-id",        "data"),
    prevent_initial_call=True,
)
def save_sentence_edit(n_clicks, idx, new_text_val, cover_letter, job_id):
    if not n_clicks or idx is None or not new_text_val or not cover_letter:
        return no_update
    cl_text = cover_letter.get("text", "") if isinstance(cover_letter, dict) else cover_letter
    import re as _re
    sentences = _re.split(r'(?<=[.!?])\s+', cl_text.strip())
    if idx >= len(sentences):
        return no_update
    sentences[idx] = new_text_val.strip()
    new_text = " ".join(sentences)
    apps = _load_apps()
    job  = next((a for a in apps if a["id"] == job_id), {}) if job_id else {}
    pdf_path = save_cover_letter_pdf(new_text, job)
    return {"text": new_text, "pdf_path": pdf_path}


# ── Masterlist: capture ✕ clicks in the browser, write key to store ────────────
# JS checks !value so n_clicks=0 (spurious Dash 4 re-mount fires) are ignored.

clientside_callback(
    """
    function() {
        var c = window.dash_clientside.callback_context;
        if (!c.triggered || !c.triggered.length || !c.triggered[0].value)
            return window.dash_clientside.no_update;
        var match = c.triggered[0].prop_id.match(/"index":"([^"]+)"/);
        return match ? match[1] : window.dash_clientside.no_update;
    }
    """,
    Output("remove-item-store", "data"),
    Input({"type": "remove-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)


# ── Masterlist: single callback — renders, adds, removes ───────────────────────

@callback(
    Output("buy-display",   "children"),
    Output("todo-display",  "children"),
    Output("watch-display", "children"),
    Output("buy-input",     "value"),
    Output("todo-input",    "value"),
    Output("watch-input",   "value"),
    Input("list-refresh-trigger", "data"),
    Input("buy-add-btn",    "n_clicks"),
    Input("todo-add-btn",   "n_clicks"),
    Input("watch-add-btn",  "n_clicks"),
    Input("remove-item-store", "data"),
    State("buy-input",   "value"),
    State("todo-input",  "value"),
    State("watch-input", "value"),
)
def manage_lists(_trigger, _nb, _nt, _nw, remove_key,
                 v_buy, v_todo, v_watch):
    triggered = ctx.triggered_id
    add_map = {
        "buy-add-btn":   ("buy",   v_buy),
        "todo-add-btn":  ("todo",  v_todo),
        "watch-add-btn": ("watch", v_watch),
    }
    if triggered in add_map:
        list_name, text = add_map[triggered]
        if text and text.strip():
            add_item(list_name, text)
    elif triggered == "remove-item-store" and remove_key and ":" in remove_key:
        list_name, item_id = remove_key.split(":", 1)
        remove_item(list_name, item_id)

    data = load_lists()
    b, t, w = data.get("buy", []), data.get("todo", []), data.get("watch", [])
    return (
        _render_items("buy",   b),
        _render_items("todo",  t),
        _render_items("watch", w),
        "" if triggered == "buy-add-btn"   else (v_buy   or ""),
        "" if triggered == "todo-add-btn"  else (v_todo  or ""),
        "" if triggered == "watch-add-btn" else (v_watch or ""),
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=True, dev_tools_ui=False, dev_tools_props_check=False)
