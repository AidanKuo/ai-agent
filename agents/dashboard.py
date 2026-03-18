"""
dashboard.py — OpenClaw Job Application Dashboard

Run with:
    streamlit run dashboard.py --server.port 8501

Access via VS Code tunnel at:
    http://localhost:8501
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import ollama
import streamlit as st
import yaml

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR  = Path(__file__).parent
APPS_PATH = BASE_DIR / "data" / "applications.json"
LOG_PATH  = BASE_DIR / "logs" / "agent.log"
CONFIG    = BASE_DIR / "config" / "settings.yaml"
RESUME    = BASE_DIR / "profile" / "resume.tex"
CL_STYLE  = BASE_DIR / "profile" / "cover_letter_template.md"
LETTERS   = BASE_DIR / "data" / "cover_letters"

st.set_page_config(
    page_title="OpenClaw Dashboard",
    page_icon="🦞",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styles ────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}
.stApp {
    background: #0f0f0f;
    color: #e8e6e0;
}
[data-testid="stSidebar"] {
    background: #161616;
    border-right: 1px solid #2a2a2a;
}
.metric-card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 0;
}
.metric-label {
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #666;
    margin-bottom: 6px;
}
.metric-value {
    font-family: 'DM Mono', monospace;
    font-size: 28px;
    font-weight: 500;
    color: #e8e6e0;
    line-height: 1;
}
.metric-value.green { color: #4ade80; }
.metric-value.amber { color: #fbbf24; }
.metric-value.red   { color: #f87171; }
.job-card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 10px;
    padding: 1rem 1.25rem;
    margin-bottom: 10px;
    transition: border-color 0.15s;
}
.job-card:hover { border-color: #444; }
.job-card.selected { border-color: #4ade80; }
.job-title {
    font-size: 15px;
    font-weight: 600;
    color: #e8e6e0;
    margin-bottom: 3px;
}
.job-meta {
    font-size: 12px;
    color: #888;
    margin-bottom: 8px;
}
.score-pill {
    display: inline-block;
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    font-weight: 500;
    padding: 2px 8px;
    border-radius: 20px;
    margin-right: 6px;
}
.score-high  { background: #14532d; color: #4ade80; }
.score-mid   { background: #713f12; color: #fbbf24; }
.score-low   { background: #450a0a; color: #f87171; }
.log-box {
    background: #0a0a0a;
    border: 1px solid #1e1e1e;
    border-radius: 8px;
    padding: 1rem;
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    color: #888;
    height: 340px;
    overflow-y: auto;
    line-height: 1.7;
}
.log-line.info    { color: #9ca3af; }
.log-line.error   { color: #f87171; }
.log-line.warning { color: #fbbf24; }
.log-line.success { color: #4ade80; }
.section-header {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #555;
    padding-bottom: 8px;
    border-bottom: 1px solid #1e1e1e;
    margin-bottom: 16px;
}
.cover-letter-box {
    background: #111;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 1.25rem;
    font-size: 13px;
    line-height: 1.8;
    color: #ccc;
    white-space: pre-wrap;
    font-family: 'DM Sans', sans-serif;
}
.reasoning-box {
    background: #1a1a1a;
    border-left: 3px solid #374151;
    padding: 8px 12px;
    border-radius: 0 6px 6px 0;
    font-size: 12px;
    color: #888;
    margin-top: 6px;
    font-style: italic;
}
div[data-testid="stButton"] button {
    border-radius: 8px;
    font-family: 'DM Sans', sans-serif;
    font-weight: 500;
    transition: all 0.15s;
}
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def load_applications():
    if not APPS_PATH.exists():
        return []
    with open(APPS_PATH) as f:
        return json.load(f)


def save_applications(apps):
    with open(APPS_PATH, "w") as f:
        json.dump(apps, f, indent=2)
    st.cache_data.clear()


def load_config():
    with open(CONFIG) as f:
        return yaml.safe_load(f)


def load_resume_text():
    if not RESUME.exists():
        return ""
    import re
    raw = RESUME.read_text(encoding="utf-8")
    raw = re.sub(r"\\[a-zA-Z]+\*?(\[.*?\])?\{(.*?)\}", r"\2", raw)
    raw = re.sub(r"\\[a-zA-Z]+", " ", raw)
    raw = re.sub(r"[{}]", " ", raw)
    raw = re.sub(r"%.*", "", raw)
    return re.sub(r"\s+", " ", raw).strip()[:3000]


def load_log_lines(n=80):
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
        return f.readlines()[-n:]


def score_color(score):
    if score is None:
        return "score-low", "?"
    if score >= 8:
        return "score-high", f"{score}/10"
    if score >= 6:
        return "score-mid", f"{score}/10"
    return "score-low", f"{score}/10"


def generate_cover_letter(job, cfg):
    resume   = load_resume_text()
    style    = CL_STYLE.read_text(encoding="utf-8") if CL_STYLE.exists() else ""
    model    = cfg["model"]["name"]

    prompt = f"""Write a tailored cover letter.

CANDIDATE RESUME:
{resume}

COVER LETTER STYLE GUIDE:
{style}

JOB:
Title: {job.get('title','')}
Company: {job.get('company','')}
Location: {job.get('location','')}
Description: {job.get('description','')[:2000]}

Instructions:
- Follow the style guide exactly
- Highlight the most relevant project
- Include one metric from the resume
- 250-350 words
- No date or address header
- Output cover letter text only"""

    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.4},
    )
    letter = response["message"]["content"].strip()

    humanize_prompt = f"""Rewrite this cover letter to sound like a real person wrote it.
Keep all facts, metrics, and structure identical.
Remove AI giveaways: hollow enthusiasm, corporate filler, perfectly balanced rhythm.
Use contractions. Vary sentence length. Short sentences for emphasis.
Output rewritten letter only.

{letter}"""

    response2 = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": humanize_prompt}],
        options={"temperature": 0.6},
    )
    return response2["message"]["content"].strip()


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🦞 OpenClaw")
    st.markdown("---")

    page = st.radio(
        "Navigate",
        ["Apply queue", "Pipeline logs", "All applications"],
        label_visibility="collapsed",
    )

    st.markdown("---")

    apps = load_applications()
    total    = len(apps)
    applied  = sum(1 for a in apps if a.get("status") == "applied")
    queued   = sum(1 for a in apps if a.get("status") == "auto_apply")
    review   = sum(1 for a in apps if a.get("status") == "needs_review")

    st.markdown(f"""
<div class="metric-card" style="margin-bottom:8px">
    <div class="metric-label">Applied</div>
    <div class="metric-value green">{applied}</div>
</div>
<div class="metric-card" style="margin-bottom:8px">
    <div class="metric-label">In queue</div>
    <div class="metric-value amber">{queued}</div>
</div>
<div class="metric-card">
    <div class="metric-label">Needs review</div>
    <div class="metric-value">{review}</div>
</div>
""", unsafe_allow_html=True)

    st.markdown("---")

    if st.button("Run pipeline now", use_container_width=True):
        with st.spinner("Starting pipeline..."):
            subprocess.Popen(
                [sys.executable, str(BASE_DIR / "run_pipeline.py")],
                cwd=str(BASE_DIR),
            )
        st.success("Pipeline started — check logs tab")

    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ── Page: Apply queue ─────────────────────────────────────────────────────────

if page == "Apply queue":
    st.markdown('<div class="section-header">Apply queue</div>', unsafe_allow_html=True)

    cfg   = load_config()
    apps  = load_applications()
    queue = [a for a in apps if a.get("status") == "auto_apply" and not a.get("applied_at")]

    if not queue:
        st.info("Queue is empty — run the pipeline to scrape and score new jobs.")
        st.stop()

    max_apply = cfg["scoring"]["max_applications_per_day"]
    applied_today = sum(
        1 for a in apps
        if a.get("status") == "applied"
        and a.get("applied_at", "")[:10] == datetime.now().strftime("%Y-%m-%d")
    )

    st.markdown(
        f"**{len(queue)} jobs ready** — {applied_today}/{max_apply} applied today",
        unsafe_allow_html=False,
    )

    st.markdown("---")

    for i, job in enumerate(queue):
        pill_class, pill_text = score_color(job.get("score"))
        job_key = job["id"][:8]

        with st.container():
            col1, col2 = st.columns([3, 1])

            with col1:
                st.markdown(f"""
<div class="job-card">
    <div class="job-title">{job.get('title','—')}</div>
    <div class="job-meta">{job.get('company','—')} · {job.get('location','—')} · {job.get('site','—').capitalize()}</div>
    <span class="score-pill {pill_class}">{pill_text}</span>
    {'<span style="font-size:11px;color:#4ade80;font-family:DM Mono,monospace">Remote</span>' if job.get('is_remote') else ''}
</div>
""", unsafe_allow_html=True)

                if job.get("reasoning"):
                    st.markdown(f'<div class="reasoning-box">{job["reasoning"]}</div>', unsafe_allow_html=True)

            with col2:
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                if st.button("Open job", key=f"open_{job_key}", use_container_width=True):
                    url = job.get("job_url", "")
                    if url:
                        st.markdown(f'<meta http-equiv="refresh" content="0;url={url}">', unsafe_allow_html=True)
                        st.markdown(f"[Click here if not redirected]({url})")

                # Cover letter toggle
                cl_key = f"cl_generated_{job_key}"
                if cl_key not in st.session_state:
                    st.session_state[cl_key] = None

                if st.button("Generate cover letter", key=f"gen_{job_key}", use_container_width=True):
                    with st.spinner("Writing + humanizing..."):
                        try:
                            letter = generate_cover_letter(job, cfg)
                            st.session_state[cl_key] = letter
                            LETTERS.mkdir(exist_ok=True)
                            import re
                            fname = f"{datetime.now().strftime('%Y%m%d')}_{re.sub(r'[^\\w]','_',job.get('company','co'))[:30]}_{re.sub(r'[^\\w]','_',job.get('title','role'))[:30]}.txt"
                            (LETTERS / fname).write_text(letter, encoding="utf-8")
                        except Exception as e:
                            st.error(f"Generation failed: {e}")

                if st.button("Mark applied", key=f"apply_{job_key}", use_container_width=True, type="primary"):
                    for a in apps:
                        if a["id"] == job["id"]:
                            a["status"]     = "applied"
                            a["applied_at"] = datetime.utcnow().isoformat()
                            break
                    save_applications(apps)
                    st.success(f"Marked as applied!")
                    st.rerun()

                if st.button("Skip", key=f"skip_{job_key}", use_container_width=True):
                    for a in apps:
                        if a["id"] == job["id"]:
                            a["status"] = "skipped"
                            break
                    save_applications(apps)
                    st.rerun()

        # Show cover letter if generated
        if st.session_state.get(cl_key):
            with st.expander("Cover letter — click to expand/edit", expanded=True):
                edited = st.text_area(
                    "Edit before submitting",
                    value=st.session_state[cl_key],
                    height=320,
                    key=f"cl_edit_{job_key}",
                    label_visibility="collapsed",
                )
                st.session_state[cl_key] = edited

                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("Copy to clipboard", key=f"copy_{job_key}"):
                        st.code(edited, language=None)
                with col_b:
                    if st.button("Save edits", key=f"save_{job_key}"):
                        LETTERS.mkdir(exist_ok=True)
                        import re
                        fname = f"{datetime.now().strftime('%Y%m%d')}_{re.sub(r'[^\\w]','_',job.get('company','co'))[:30]}_{re.sub(r'[^\\w]','_',job.get('title','role'))[:30]}.txt"
                        (LETTERS / fname).write_text(edited, encoding="utf-8")
                        st.success("Saved.")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


# ── Page: Pipeline logs ───────────────────────────────────────────────────────

elif page == "Pipeline logs":
    st.markdown('<div class="section-header">Pipeline logs</div>', unsafe_allow_html=True)

    auto_refresh = st.checkbox("Auto-refresh every 5 seconds", value=False)

    lines = load_log_lines(100)

    log_html = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "[ERROR]" in line:
            css = "error"
        elif "[WARNING]" in line:
            css = "warning"
        elif any(w in line for w in ["complete", "saved", "Applied", "✓"]):
            css = "success"
        else:
            css = "info"
        safe = line.replace("<", "&lt;").replace(">", "&gt;")
        log_html += f'<div class="log-line {css}">{safe}</div>\n'

    st.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)

    if auto_refresh:
        time.sleep(5)
        st.rerun()

    if st.button("Refresh logs"):
        st.rerun()


# ── Page: All applications ────────────────────────────────────────────────────

elif page == "All applications":
    st.markdown('<div class="section-header">All applications</div>', unsafe_allow_html=True)

    apps = load_applications()

    status_filter = st.selectbox(
        "Filter by status",
        ["All", "applied", "auto_apply", "needs_review", "skipped", "rejected", "scraped"],
    )

    filtered = apps if status_filter == "All" else [a for a in apps if a.get("status") == status_filter]
    filtered = sorted(filtered, key=lambda x: x.get("score") or 0, reverse=True)

    st.markdown(f"**{len(filtered)} jobs**")
    st.markdown("---")

    for job in filtered:
        pill_class, pill_text = score_color(job.get("score"))
        status = job.get("status", "unknown")
        status_colors = {
            "applied":       "#14532d",
            "auto_apply":    "#713f12",
            "needs_review":  "#1e3a5f",
            "skipped":       "#1f1f1f",
            "rejected":      "#450a0a",
            "scraped":       "#1a1a1a",
        }
        bg = status_colors.get(status, "#1a1a1a")

        st.markdown(f"""
<div class="job-card" style="border-left: 3px solid {bg}; padding-left: 14px;">
    <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
            <div class="job-title">{job.get('title','—')}</div>
            <div class="job-meta">{job.get('company','—')} · {job.get('location','—')}</div>
        </div>
        <div style="text-align:right">
            <span class="score-pill {pill_class}">{pill_text}</span>
            <div style="font-size:10px;color:#555;margin-top:4px;font-family:'DM Mono',monospace">{status}</div>
        </div>
    </div>
    {f'<div class="reasoning-box">{job["reasoning"]}</div>' if job.get("reasoning") else ''}
</div>
""", unsafe_allow_html=True)
