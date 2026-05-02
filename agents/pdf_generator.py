"""
pdf_generator.py — Playwright-based resume PDF renderer.

Takes a tailored resume in markdown (cv.md format), fills the HTML template in
templates/cv-template.html, and renders a pixel-perfect PDF via Chromium.

Output: data/resumes/YYYYMMDD_{Company}_{Role}.pdf
        (falls back to data/resumes/Kuo_Aidan_Resume.pdf if no job provided)

Usage (CLI):
    python agents/pdf_generator.py                        # renders base cv.md
    python agents/pdf_generator.py --job JOB_ID           # renders tailored version
    python agents/pdf_generator.py --md path/to/file.md   # renders arbitrary markdown

Programmatic:
    from agents.pdf_generator import render_resume_pdf
    path = render_resume_pdf(markdown_text, job=job_dict)
"""

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR      = Path(__file__).parent.parent
CV_PATH       = BASE_DIR / "cv.md"
TEMPLATE_PATH = BASE_DIR / "templates" / "cv-template.html"
PROFILE_PATH  = BASE_DIR / "config" / "profile.yml"
RESUMES_DIR   = BASE_DIR / "data" / "resumes"
APPS_PATH     = BASE_DIR / "data" / "applications.json"


# ── Markdown → HTML ───────────────────────────────────────────────────────────

def _inline(text: str) -> str:
    """Convert inline markdown to HTML (bold, italic, links). Escapes HTML first."""
    text = html.escape(text)
    # **bold**
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # *italic*
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # [label](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _parse_markdown(md: str) -> str:
    """Convert cv.md structure into HTML body sections."""
    lines = md.splitlines()
    html_parts: list[str] = []
    i = 0

    def flush_ul(items):
        if items:
            html_parts.append("<ul>")
            for item in items:
                html_parts.append(f"  <li>{_inline(item)}</li>")
            html_parts.append("</ul>")

    current_section = None
    pending_bullets: list[str] = []
    pending_entry_open = False

    def close_entry():
        nonlocal pending_entry_open
        flush_ul(pending_bullets)
        pending_bullets.clear()
        if pending_entry_open:
            html_parts.append("</div>")  # close .entry
            pending_entry_open = False

    def close_section():
        close_entry()
        if current_section is not None:
            html_parts.append("</div>")  # close .section

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip the H1 name line and horizontal rules — header is in the template
        if stripped.startswith("# ") and i < 3:
            i += 1
            continue
        if stripped == "---":
            i += 1
            continue

        # ── H2: section header ────────────────────────────────────────────────
        if stripped.startswith("## "):
            close_section()
            title = stripped[3:].strip()
            css_extra = " summary" if title.lower() == "summary" else ""
            html_parts.append(f'<div class="section{css_extra}">')
            html_parts.append(f'  <div class="section-title">{html.escape(title)}</div>')
            current_section = title.lower()
            pending_entry_open = False
            i += 1
            continue

        # ── H3: entry title (project / leadership role) ───────────────────────
        if stripped.startswith("### "):
            close_entry()
            raw = stripped[4:].strip()

            # Format: "Title | tech1, tech2 | Date"  or  "Title | Date"
            parts = [p.strip() for p in raw.split("|")]
            title_part = parts[0]
            date_part = parts[-1] if len(parts) > 1 else ""
            tech_part  = parts[1] if len(parts) == 3 else ""

            html_parts.append('<div class="entry">')
            html_parts.append('  <div class="entry-header">')
            html_parts.append(f'    <span class="entry-title">{html.escape(title_part)}</span>')
            if date_part:
                html_parts.append(f'    <span class="entry-date">{html.escape(date_part)}</span>')
            html_parts.append("  </div>")
            if tech_part:
                html_parts.append(f'  <div class="entry-meta">{html.escape(tech_part)}</div>')
            pending_entry_open = True
            i += 1
            continue

        # ── Bullet ────────────────────────────────────────────────────────────
        if stripped.startswith("- "):
            pending_bullets.append(stripped[2:])
            i += 1
            continue

        # ── Skills section: bold-label lines ─────────────────────────────────
        if current_section == "skills" and ":" in stripped and not stripped.startswith("-"):
            flush_ul(pending_bullets)
            pending_bullets.clear()
            label, _, rest = stripped.partition(":")
            html_parts.append('<div class="skills-grid">')
            html_parts.append(
                f'  <div class="skill-row">'
                f'<span class="skill-label">{html.escape(label)}:</span> '
                f'{_inline(rest.strip())}'
                f'</div>'
            )
            html_parts.append("</div>")
            i += 1
            continue

        # ── Education: bold school lines ("**School** — City") ───────────────
        if current_section in ("education",) and stripped.startswith("**"):
            flush_ul(pending_bullets)
            pending_bullets.clear()
            # School line
            school_html = _inline(stripped)
            html_parts.append('<div class="entry">')
            html_parts.append(f'  <div class="edu-school">{school_html}</div>')
            pending_entry_open = True
            i += 1
            # Next line is usually "Degree | Date"
            if i < len(lines):
                deg_line = lines[i].strip()
                if deg_line and not deg_line.startswith("-"):
                    html_parts.append(f'  <div class="edu-degree">{_inline(deg_line)}</div>')
                    i += 1
            continue

        # ── Coursework line ───────────────────────────────────────────────────
        if current_section == "education" and stripped.lower().startswith("relevant coursework"):
            flush_ul(pending_bullets)
            pending_bullets.clear()
            html_parts.append(f'  <div class="edu-coursework">{_inline(stripped)}</div>')
            i += 1
            continue

        # ── Summary / plain paragraph ─────────────────────────────────────────
        if stripped and current_section == "summary":
            flush_ul(pending_bullets)
            pending_bullets.clear()
            html_parts.append(f'  <p>{_inline(stripped)}</p>')
            i += 1
            continue

        # ── Core Competencies grid (injected by pdf mode) ─────────────────────
        if stripped and current_section == "core competencies":
            flush_ul(pending_bullets)
            pending_bullets.clear()
            html_parts.append(f'  <div class="competencies">{_inline(stripped)}</div>')
            i += 1
            continue

        i += 1

    close_section()
    return "\n".join(html_parts)


# ── Profile ───────────────────────────────────────────────────────────────────

def _load_profile() -> dict:
    """Load config/profile.yml as a simple key-value dict (no yaml dependency)."""
    profile = {
        "name":     "Aidan Kuo",
        "email":    "aidanlkuo@gmail.com",
        "phone":    "(832) 206-5968",
        "linkedin": "linkedin.com/in/aidan-kuo",
        "github":   "github.com/aidankuo",
    }
    if not PROFILE_PATH.exists():
        return profile
    for line in PROFILE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if ":" not in line or line.startswith("#"):
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key in profile and val:
            profile[key] = val
    return profile


# ── Render ────────────────────────────────────────────────────────────────────

def render_resume_pdf(markdown_text: str, job: dict | None = None) -> str:
    """
    Render markdown resume to PDF. Returns the output file path.

    Args:
        markdown_text: Full resume content in cv.md format.
        job: Optional job dict with 'company' and 'title' for the filename.
    """
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)

    profile = _load_profile()
    body    = _parse_markdown(markdown_text)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    filled = (
        template
        .replace("{{name}}",     profile["name"])
        .replace("{{email}}",    profile["email"])
        .replace("{{phone}}",    profile["phone"])
        .replace("{{linkedin}}", profile["linkedin"])
        .replace("{{github}}",   profile["github"])
        .replace("{{body}}",     body)
    )

    # ── Output path ───────────────────────────────────────────────────────────
    date_str = datetime.now().strftime("%Y%m%d")
    if job:
        company = re.sub(r"[^\w]", "_", (job.get("company") or "").strip())[:30]
        role    = re.sub(r"[^\w]", "_", (job.get("title")   or "").strip())[:30]
        fname   = f"{date_str}_{company}_{role}.pdf"
    else:
        fname = "Kuo_Aidan_Resume.pdf"
    out_path = RESUMES_DIR / fname

    # ── Playwright render ─────────────────────────────────────────────────────
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page()
        page.set_content(filled, wait_until="domcontentloaded")
        page.pdf(
            path=str(out_path),
            format="Letter",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        browser.close()

    return str(out_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    parser = argparse.ArgumentParser(description="Render a resume PDF from markdown.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--job", metavar="JOB_ID",
                       help="Job ID from data/applications.json — renders tailored version")
    group.add_argument("--md",  metavar="FILE",
                       help="Path to a markdown file to render (default: cv.md)")
    args = parser.parse_args()

    job = None
    if args.job:
        apps = json.loads(APPS_PATH.read_text(encoding="utf-8"))
        job  = next((j for j in apps if j.get("id") == args.job), None)
        if not job:
            sys.exit(f"Job ID '{args.job}' not found in applications.json")
        md_text = CV_PATH.read_text(encoding="utf-8")
    elif args.md:
        md_text = Path(args.md).read_text(encoding="utf-8")
    else:
        md_text = CV_PATH.read_text(encoding="utf-8")

    out = render_resume_pdf(md_text, job=job)
    print(f"Saved: {out}")


if __name__ == "__main__":
    _cli()
