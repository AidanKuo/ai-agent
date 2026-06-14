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
import pandas as pd

from dash import (
    ALL, Dash, Input, Output, State, callback, clientside_callback, ctx,
    dcc, html, no_update,
)

from lib.constants import APPS_PATH, CONFIG_PATH

import yaml

# ── App init ──────────────────────────────────────────────────────────────────

app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.CYBORG],
    title="JARVIS",
    suppress_callback_exceptions=True,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_AGGREGATOR_HOSTS = {
    "indeed":        ("indeed.com", "indeed.co"),
    "linkedin":      ("linkedin.com",),
    "zip_recruiter": ("ziprecruiter.com",),
    "glassdoor":     ("glassdoor.com",),
    "google":        ("google.com",),
}


def _clean_url(value) -> str:
    """Return a usable URL string, or '' for empty/nan/None values."""
    s = str(value or "").strip()
    return "" if s.lower() in ("", "nan", "none") else s


def _url_host(url: str) -> str:
    """Return lowercase hostname (no www., no port). Empty string on parse failure."""
    from urllib.parse import urlparse
    try:
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _apply_urls(job: dict) -> tuple[str, str]:
    """Return (direct_apply_url, aggregator_url). Either may be ''.

    If job_url_direct points back to the aggregator's own domain (e.g. an
    Indeed-hosted apply form), it's NOT a true direct link — return '' for it.
    """
    direct = _clean_url(job.get("job_url_direct"))
    agg    = _clean_url(job.get("job_url"))
    site   = (job.get("site") or "").lower()
    blocked_hosts = _AGGREGATOR_HOSTS.get(site, ())
    if direct and blocked_hosts:
        host = _url_host(direct)
        if any(host == h or host.endswith("." + h) for h in blocked_hosts):
            direct = ""
    return direct, agg


def _best_apply_url(job: dict) -> str:
    """Prefer direct ATS link over aggregator link. Returns '' if neither exists."""
    direct, agg = _apply_urls(job)
    return direct or agg


def _source_category(job: dict) -> str:
    """Classify the apply path. Used for filter buttons.

    Returns one of: 'apply_direct', 'indeed', 'linkedin', 'easy_apply', 'other'

    Note: 'easy_apply' is heuristic — LinkedIn jobs without a usable direct URL
    are *likely* Easy Apply (or auth-walled), but we can't tell with certainty
    without an authenticated LinkedIn session.
    """
    direct, _ = _apply_urls(job)
    site = (job.get("site") or "").lower()
    if site == "linkedin":
        return "linkedin" if direct else "easy_apply"
    if direct:
        return "apply_direct"
    if site == "indeed":
        return "indeed"
    return "other"


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
        "URL":         _best_apply_url(j),
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

def _info_row(key, val, val_class=""):
    return html.Div([
        html.Span(key, className="info-key"),
        html.Span(val, className=f"info-val {val_class}"),
    ], className="info-row")


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

# Source filters — shown as chips on a second row; filter by apply-path category.
# Note: "Easy Apply" includes true LinkedIn Easy Apply jobs AND jobs where
# LinkedIn's apply button redirects externally (we can't distinguish without auth).
SOURCE_FILTERS = [
    ("source_all",          "All Sources"),
    ("source_apply_direct", "Direct"),
    ("source_indeed",       "Indeed"),
    ("source_linkedin",     "LinkedIn"),
    ("source_easy_apply",   "Easy Apply"),
]

# Combined — used by filter callbacks
FILTERS = ACTION_FILTERS + STAT_FILTERS


def _pipeline_tab():
    _divider = html.Span(style={
        "display": "inline-block", "width": "1px", "height": "16px",
        "background": "#1a3040", "verticalAlign": "middle", "margin": "0 4px",
    })

    _default_filter = "auto_apply"
    action_btns = [
        dbc.Button(
            [label, html.Span("0", id={"type": "filter-count", "index": status},
                               className="filter-count-badge")],
            id={"type": "filter-btn", "index": status},
            size="sm",
            className="filter-active" if status == _default_filter else "",
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
    _default_source = "source_all"
    source_chips = [
        html.Span(
            [label, " ",
             html.Span("0", id={"type": "source-count", "index": key},
                       style={"fontWeight": "600", "color": "#6a8aaa"})],
            id={"type": "source-btn", "index": key},
            n_clicks=0,
            className="stat-chip filter-active" if key == _default_source else "stat-chip",
            style={"cursor": "pointer"},
        )
        for key, label in SOURCE_FILTERS
    ]
    return html.Div([
        # Pipeline progress banner
        html.Div(id="panel-pipeline-progress", className="mb-2"),

        # Row 1: primary action filters + bulk actions
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
        ], className="filter-toolbar"),

        # Row 2: source chips (left) + group filter & refresh (right)
        html.Div([
            *source_chips,
            html.Div(style={"flex": "1"}),
            dcc.Dropdown(
                id="group-filter-dropdown",
                options=GROUP_OPTIONS,
                value="all",
                clearable=False,
                style={"width": "180px"},
            ),
            dbc.Button("↺", id="btn-refresh-jobs", size="sm",
                       color="secondary", outline=True,
                       title="Reload jobs from disk",
                       style={"fontSize": "13px", "padding": "2px 10px"}),
        ], className="filter-toolbar", style={"marginBottom": "12px"}),

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


# ── Sidebar nav pages ─────────────────────────────────────────────────────────

PAGES = [("dashboard", "Dashboard", "▣")]


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
        ], className="sidebar-brand"),

        # Nav
        html.Div([
            html.Div([
                html.Span(icon, className="nav-icon"),
                html.Span(label),
            ], id={"type": "nav-item", "index": page_id},
               className="nav-item active" if page_id == "dashboard" else "nav-item",
               n_clicks=0)
            for page_id, label, icon in PAGES
        ], className="sidebar-nav"),
    ], className="sidebar"),

    # Main content
    html.Div([
        html.Div(_pipeline_tab(), id="page-dashboard", style={"display": "block"}),

        # All stores
        dcc.Store(id="selected-job-id",    data=None),
        dcc.Store(id="status-filter",      data="auto_apply"),
        dcc.Store(id="group-filter",       data="all"),
        dcc.Store(id="source-filter",      data="source_all"),
        dcc.Store(id="job-list-version",   data=0),
        dcc.Store(id="active-page",          data="dashboard"),
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
    Output("page-dashboard", "style"),
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


# ── Pipeline panel callback ───────────────────────────────────────────────────

@callback(
    Output("panel-pipeline-progress", "children"),
    Input("tick", "n_intervals"),
)
def refresh_pipeline_panel(_n):
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

    return pipeline_progress_panel


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


# ── Pipeline: source filter ───────────────────────────────────────────────────

@callback(
    Output("source-filter", "data"),
    Output({"type": "source-btn", "index": ALL}, "className"),
    Input({"type": "source-btn", "index": ALL}, "n_clicks"),
    State({"type": "source-btn", "index": ALL}, "id"),
    State("source-filter", "data"),
    prevent_initial_call=True,
)
def update_source_filter(_n_clicks, ids, current):
    triggered = ctx.triggered_id
    active = triggered["index"] if triggered else (current or "source_all")
    classes = [
        ("stat-chip filter-active" if id_["index"] == active else "stat-chip")
        for id_ in ids
    ]
    return active, classes


@callback(
    Output({"type": "source-count", "index": ALL}, "children"),
    Input("tick", "n_intervals"),
    Input("status-filter", "data"),
    Input("group-filter", "data"),
    State({"type": "source-count", "index": ALL}, "id"),
)
def refresh_source_counts(_n, status_filter, group_filter, ids):
    apps = _load_apps()
    if status_filter and status_filter != "all":
        apps = [a for a in apps if a.get("status") == status_filter]
    if group_filter and group_filter != "all":
        apps = [a for a in apps if a.get("search_group") == group_filter]
    counts = {"source_all": len(apps)}
    for a in apps:
        cat = "source_" + _source_category(a)
        counts[cat] = counts.get(cat, 0) + 1
    return [str(counts.get(id_["index"], 0)) for id_ in ids]


# ── Pipeline: job list ────────────────────────────────────────────────────────

@callback(
    Output("job-list", "children"),
    Input("status-filter", "data"),
    Input("group-filter", "data"),
    Input("source-filter", "data"),
    Input("job-list-version", "data"),
)
def render_job_list(status_filter, group_filter, source_filter, _version):
    all_apps = _load_apps()
    apps = all_apps
    if status_filter and status_filter != "all":
        apps = [a for a in apps if a.get("status") == status_filter]

    # Filter by search group when a specific group is selected
    if group_filter and group_filter != "all":
        apps = [a for a in apps if a.get("search_group") == group_filter]

    # Filter by apply-path source category
    if source_filter and source_filter != "source_all":
        target = source_filter.removeprefix("source_")
        apps = [a for a in apps if _source_category(a) == target]

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
        return html.Div([
            html.Div("○", className="empty-icon"),
            html.Div("No jobs in this category"),
        ], className="empty-state")

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
        ], id={"type": "job-item", "index": job_id}, className="job-item",
           style={"borderLeft": f"3px solid {color}"}, n_clicks=0))

    if total > 200:
        items.append(html.Div(
            f"Showing 200 of {total} — apply or skip to see more",
            style={"fontSize": "11px", "color": "#4a6a82", "textAlign": "center", "padding": "8px"},
        ))

    return items


# ── Pipeline: select job ──────────────────────────────────────────────────────

@callback(
    Output("selected-job-id", "data"),
    Input({"type": "job-item", "index": ALL}, "n_clicks"),
    State("selected-job-id", "data"),
    prevent_initial_call=True,
)
def select_job(n_clicks, current_id):
    triggered = ctx.triggered_id
    if not triggered or not isinstance(triggered, dict):
        return no_update
    new_id = triggered["index"]
    if new_id == current_id:
        return no_update
    return new_id


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
    Input("selected-job-id", "data"),
)
def render_detail(job_id):
    if not job_id:
        return html.Div(
            html.Div([
                html.Div("◈", className="empty-icon"),
                html.Div("Select a job to view details"),
            ], className="empty-state"),
            className="info-panel",
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
    direct_url, agg_url = _apply_urls(job)
    site = (job.get("site") or "").lower()
    site_label = {
        "linkedin": "LinkedIn",
        "indeed":   "Indeed",
        "zip_recruiter": "ZipRecruiter",
        "greenhouse": "Greenhouse",
        "ashby": "Ashby",
        "lever": "Lever",
    }.get(site, "Posting")

    link_row: list = []
    if direct_url:
        # Direct ATS link — strongest CTA. Skip the aggregator link to avoid clutter.
        link_row.append(html.A("Apply Direct →", href=direct_url, target="_blank",
                               className="metric-pill pill-green",
                               style={"fontSize": "10px", "textDecoration": "none"}))
    elif agg_url:
        # No direct URL — fall back to aggregator (LinkedIn / Indeed posting page).
        link_row.append(html.A(f"View on {site_label} →", href=agg_url, target="_blank",
                               className="metric-pill pill-grey",
                               style={"fontSize": "10px", "textDecoration": "none",
                                      "color": "#5a8aaa"}))

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
            *link_row,
        ], className="mb-2", style={"display": "flex", "alignItems": "center",
                                    "gap": "4px", "flexWrap": "wrap"}),
    ])

    # ── Actions (all statuses) ────────────────────────────────────────────────
    actions = html.Div([
        html.Div([
            dbc.Button("Mark Applied", id="btn-mark-applied", size="sm",
                       color="success", outline=True, className="me-2",
                       disabled=(status == "applied")),
            dbc.Button("Skip", id="btn-skip", size="sm",
                       color="secondary", outline=True, className="me-2",
                       disabled=(status == "skipped")),
        ], className="mb-2"),
        html.Div([
            dcc.Dropdown(
                id="status-change-dropdown",
                options=[{"label": v, "value": k} for k, v in STATUS_LABELS.items()],
                value=status,
                clearable=False,
                style={"width": "165px", "fontSize": "11px", "flexShrink": "0"},
            ),
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

    return html.Div([
        info_header,
        actions,
        html.Div(info_tab, className="pt-2"),
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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=True, dev_tools_ui=False, dev_tools_props_check=False)
