import json
import logging
import os
import re
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import ollama
import yaml
from dotenv import load_dotenv

# ── Setup ─────────────────────────────────────────────────────────────────────

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

BASE_DIR     = Path(__file__).parent.parent
CONFIG       = BASE_DIR / "config" / "settings.yaml"
APPS_PATH    = BASE_DIR / "data" / "applications.json"
RESUME       = BASE_DIR / "profile" / "resume.tex"
PREFS        = BASE_DIR / "profile" / "preferences.md"
CL_TEMPLATE  = BASE_DIR / "profile" / "cover_letter_template.md"
LETTERS_DIR  = BASE_DIR / "data" / "cover_letters"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG) as f:
        return yaml.safe_load(f)


def load_applications() -> list[dict]:
    if not APPS_PATH.exists():
        return []
    with open(APPS_PATH) as f:
        return json.load(f)


def save_applications(apps: list[dict]) -> None:
    with open(APPS_PATH, "w") as f:
        json.dump(apps, f, indent=2)


def load_resume_text() -> str:
    if not RESUME.exists():
        return ""
    raw = RESUME.read_text(encoding="utf-8")
    raw = re.sub(r"\\[a-zA-Z]+\*?(\[.*?\])?\{(.*?)\}", r"\2", raw)
    raw = re.sub(r"\\[a-zA-Z]+", " ", raw)
    raw = re.sub(r"[{}]", " ", raw)
    raw = re.sub(r"%.*", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:3000]


def load_cover_letter_template() -> str:
    if not CL_TEMPLATE.exists():
        return ""
    return CL_TEMPLATE.read_text(encoding="utf-8")


def safe_filename(text: str) -> str:
    """Convert a string to a safe filename."""
    return re.sub(r"[^\w\-]", "_", text)[:40]


# ── Cover letter generator ────────────────────────────────────────────────────

COVER_LETTER_PROMPT = """You are a professional cover letter writer. Write a tailored cover letter.

CANDIDATE RESUME:
{resume}

COVER LETTER STYLE GUIDE (follow this exactly):
{style_guide}

JOB TO APPLY FOR:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Instructions:
- Follow the style guide structure and tone precisely
- Highlight the most relevant project from the resume for this specific role
- Include one specific detail about the company from the job description
- Include at least one achievement metric from the resume
- Keep it 250-350 words
- Do not include a date or address header
- End with the signature block from the style guide
- Output the cover letter text only, nothing else"""


def generate_cover_letter(job: dict, resume: str, style_guide: str, cfg: dict) -> str:
    model = cfg["model"]["name"]

    prompt = COVER_LETTER_PROMPT.format(
        resume=resume,
        style_guide=style_guide,
        title=job.get("title", ""),
        company=job.get("company", ""),
        location=job.get("location", ""),
        description=job.get("description", "")[:2000],
    )

    log.info(f"  Generating cover letter with {model}...")
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.4},
        )
        return response["message"]["content"].strip()
    except Exception as e:
        log.error(f"Cover letter generation failed: {e}")
        return ""


HUMANIZER_PROMPT = """You are an editor. A cover letter was written by an AI and needs to sound like it was written by a real person.

ORIGINAL COVER LETTER:
{letter}

Rewrite it following these rules:
- Keep every fact, achievement, and metric exactly as stated — do not invent or remove anything
- Keep the same structure and length (250-350 words)
- Remove any of these AI giveaways:
  * Overly formal openers ("I am writing to express...")
  * Hollow enthusiasm ("I am thrilled/excited/passionate...")
  * Corporate filler ("leverage", "utilize", "synergy", "dynamic team")
  * Perfectly balanced sentence rhythm — vary sentence length
  * Lists of three adjectives ("dedicated, hardworking, and passionate")
- Replace with natural human writing:
  * Direct, confident tone — like a capable person talking to a peer
  * Occasional sentence fragments are fine
  * Contractions are fine (I've, I'm, that's)
  * One sentence can be short. For emphasis.
- Do not add new content, do not change the signature block
- Output the rewritten cover letter only, nothing else"""


def humanize_cover_letter(letter: str, cfg: dict) -> str:
    """Run a second pass to strip AI writing patterns."""
    model = cfg["model"]["name"]
    prompt = HUMANIZER_PROMPT.format(letter=letter)
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.6},
        )
        return response["message"]["content"].strip()
    except Exception as e:
        log.error(f"Humanizer failed: {e} — using original")
        return letter


def save_cover_letter(job: dict, letter: str) -> Path:
    """Save cover letter as .txt file, return the path."""
    LETTERS_DIR.mkdir(parents=True, exist_ok=True)
    company  = safe_filename(job.get("company", "company"))
    title    = safe_filename(job.get("title", "role"))
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{date_str}_{company}_{title}.txt"
    path     = LETTERS_DIR / filename
    path.write_text(letter, encoding="utf-8")
    return path


# ── Pre-fill helper ───────────────────────────────────────────────────────────

def extract_prefill_data() -> dict:
    """
    Pull contact info from resume.tex for form pre-filling.
    Returns a dict of common application fields.
    """
    raw = RESUME.read_text(encoding="utf-8") if RESUME.exists() else ""

    email_match = re.search(r"href\{mailto:([^}]+)\}", raw)
    phone_match = re.search(r"small\s+([\(\d\)\s\-\.]+\d)", raw)
    linkedin_match = re.search(r"linkedin\.com/in/([^\}\"]+)", raw)
    github_match = re.search(r"github\.com/([^\}\"]+)", raw)
    name_match = re.search(r"scshape\s+([A-Z][a-z]+\s+[A-Z][a-z]+)", raw)

    return {
        "full_name":    name_match.group(1).strip()   if name_match   else "Aidan Kuo",
        "email":        email_match.group(1).strip()  if email_match  else "",
        "phone":        phone_match.group(1).strip()  if phone_match  else "",
        "linkedin_url": f"https://linkedin.com/in/{linkedin_match.group(1).strip()}" if linkedin_match else "",
        "github_url":   f"https://github.com/{github_match.group(1).strip()}"        if github_match   else "",
    }


# ── Keyword gap report ───────────────────────────────────────────────────────

KEYWORD_GAP_PROMPT = """You are an ATS keyword analyst. Compare this job description against the candidate's resume and identify keyword gaps.

CANDIDATE RESUME (plain text):
{resume}

JOB DESCRIPTION:
Title: {title}
Company: {company}
{description}

Task:
1. Extract the 10 most important keywords/skills/tools from the job description
2. Check each against the resume
3. For missing keywords, decide if they are genuinely addable (candidate has related experience) or should be skipped (no real basis)

Respond in EXACTLY this format, nothing else:

MISSING (worth adding):
- keyword | where to add it in the resume (e.g. "Skills section" or "CSV Bot bullet")

ALREADY COVERED:
- keyword | where it appears in resume

SKIP (no real basis):
- keyword | reason"""


def generate_keyword_gap(job: dict, resume: str, cfg: dict) -> str:
    """Ask Qwen3 to compare job keywords against the resume."""
    model = cfg["model"]["name"]
    prompt = KEYWORD_GAP_PROMPT.format(
        resume=resume,
        title=job.get("title", ""),
        company=job.get("company", ""),
        description=job.get("description", "")[:2000],
    )
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
        )
        return response["message"]["content"].strip()
    except Exception as e:
        log.error(f"Keyword gap analysis failed: {e}")
        return ""


def print_keyword_gap(gap_report: str) -> None:
    print(f"\n{'─'*60}")
    print("KEYWORD GAP REPORT")
    print(f"{'─'*60}")
    print(gap_report)
    print(f"{'─'*60}")
    print("Edit profile/resume.tex now if anything is worth adding,")
    print("then recompile before submitting (Ctrl+S in VS Code).")
    print(f"{'─'*60}")


# ── Application launcher ──────────────────────────────────────────────────────

def print_application_pack(job: dict, letter: str, letter_path: Path, prefill: dict) -> None:
    """Print everything needed to complete the application manually."""
    print(f"\n{'='*60}")
    print(f"APPLICATION PACK")
    print(f"{'='*60}")
    print(f"Role:     {job['title']}")
    print(f"Company:  {job['company']}")
    print(f"Location: {job['location']}")
    print(f"Score:    {job.get('score', '?')}/10")
    print(f"URL:      {job.get('job_url', 'N/A')}")
    print(f"{'─'*60}")
    print(f"FORM FIELDS (copy-paste ready):")
    print(f"  Full name:  {prefill['full_name']}")
    print(f"  Email:      {prefill['email']}")
    print(f"  Phone:      {prefill['phone']}")
    print(f"  LinkedIn:   {prefill['linkedin_url']}")
    print(f"  GitHub:     {prefill['github_url']}")
    print(f"{'─'*60}")
    print(f"COVER LETTER saved to:")
    print(f"  {letter_path}")
    print(f"{'─'*60}")
    print(f"COVER LETTER PREVIEW:")
    print()
    print(letter)
    print(f"{'='*60}")


def open_job_url(url: str) -> None:
    """Open the job URL in the default browser."""
    if not url or url == "None":
        log.warning("No URL available for this job")
        return
    log.info(f"  Opening browser: {url}")
    webbrowser.open(url)


# ── Core applicator ───────────────────────────────────────────────────────────

def run_applicator(dry_run: bool = False) -> None:
    cfg        = load_config()
    resume     = load_resume_text()
    style      = load_cover_letter_template()
    apps       = load_applications()
    prefill    = extract_prefill_data()
    max_today  = cfg["scoring"]["max_applications_per_day"]

    # Only process approved jobs not yet applied
    queue = [
        j for j in apps
        if j.get("status") == "auto_apply"
        and not j.get("applied_at")
    ]

    if not queue:
        print("✓ No jobs in the apply queue. Run scorer + notifier first.")
        return

    # Respect daily limit
    queue = queue[:max_today]
    log.info(f"Apply queue: {len(queue)} jobs (daily limit: {max_today})")

    applied_count = 0

    for i, job in enumerate(queue):
        print(f"\n[{i+1}/{len(queue)}] {job['title']} @ {job['company']}")

        # Generate cover letter
        letter = generate_cover_letter(job, resume, style, cfg)
        if not letter:
            log.warning(f"  Skipping — cover letter generation failed")
            continue

        # Humanize the cover letter
        log.info(f"  Humanizing cover letter...")
        letter = humanize_cover_letter(letter, cfg)

        # Save cover letter to file
        letter_path = save_cover_letter(job, letter)
        log.info(f"  Cover letter saved: {letter_path.name}")

        # Generate and print keyword gap report
        log.info(f"  Running keyword gap analysis...")
        gap_report = generate_keyword_gap(job, resume, cfg)
        if gap_report:
            print_keyword_gap(gap_report)

        # Print the full application pack
        print_application_pack(job, letter, letter_path, prefill)

        if dry_run:
            print("\n[DRY RUN] Browser would open here. Job not marked as applied.")
            continue

        # Ask for confirmation before opening browser
        print(f"\nPress ENTER to open the job URL and mark as applied.")
        print(f"Type 'skip' to skip this job, 'quit' to stop.")
        choice = input("> ").strip().lower()

        if choice == "quit":
            log.info("User quit applicator early")
            break
        elif choice == "skip":
            log.info(f"  Skipped by user: {job['title']} @ {job['company']}")
            continue
        else:
            # Open browser
            open_job_url(job.get("job_url", ""))

            # Mark as applied
            for app in apps:
                if app["id"] == job["id"]:
                    app["status"]     = "applied"
                    app["applied_at"] = datetime.utcnow().isoformat()
                    app["cover_letter_path"] = str(letter_path)
                    break

            save_applications(apps)
            applied_count += 1
            log.info(f"  Marked as applied: {job['title']} @ {job['company']}")

            # Small gap between applications
            if i < len(queue) - 1:
                print("\nNext application in 3 seconds...")
                time.sleep(3)

    print(f"\n{'='*60}")
    print(f"SESSION COMPLETE")
    print(f"  Applied:    {applied_count}")
    print(f"  Remaining:  {len(queue) - applied_count}")
    print(f"  Letters in: data/cover_letters/")
    print(f"{'='*60}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("Running in DRY RUN mode — no browser will open, no jobs marked as applied.")
    run_applicator(dry_run=dry_run)
