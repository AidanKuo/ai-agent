import json
import logging
import re
import time
from pathlib import Path

import ollama
import yaml
from dotenv import load_dotenv
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).parent.parent))
from agents.ats_scanner import scan_job as ats_scan_job

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

BASE_DIR  = Path(__file__).parent.parent
CONFIG    = BASE_DIR / "config" / "settings.yaml"
APPS_PATH = BASE_DIR / "data" / "applications.json"
RESUME    = BASE_DIR / "profile" / "resume.tex"
PREFS     = BASE_DIR / "profile" / "preferences.md"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG) as f:
        return yaml.safe_load(f)


def load_resume_text() -> str:
    """Strip LaTeX commands and return plain text from resume.tex."""
    if not RESUME.exists():
        log.warning("resume.tex not found")
        return ""
    raw = RESUME.read_text(encoding="utf-8")
    # Remove LaTeX commands and environments
    raw = re.sub(r"\\[a-zA-Z]+\*?(\[.*?\])?\{(.*?)\}", r"\2", raw)
    raw = re.sub(r"\\[a-zA-Z]+", " ", raw)
    raw = re.sub(r"[{}]", " ", raw)
    raw = re.sub(r"%.*", "", raw)           # comments
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:3000]                        # cap for context window


def load_preferences_text() -> str:
    if not PREFS.exists():
        return ""
    return PREFS.read_text(encoding="utf-8")[:2000]


def load_applications() -> list[dict]:
    if not APPS_PATH.exists():
        return []
    with open(APPS_PATH) as f:
        return json.load(f)


def save_applications(apps: list[dict]) -> None:
    with open(APPS_PATH, "w") as f:
        json.dump(apps, f, indent=2)


def parse_score(response: str) -> tuple[int, str]:
    """Extract score (1-10) and reasoning from model response."""
    # Look for SCORE: N pattern
    match = re.search(r"SCORE:\s*([0-9]|10)", response, re.IGNORECASE)
    score = int(match.group(1)) if match else 0

    # Extract reasoning — everything after REASONING:
    reasoning_match = re.search(r"REASONING:\s*(.+)", response, re.IGNORECASE | re.DOTALL)
    reasoning = reasoning_match.group(1).strip()[:500] if reasoning_match else response[:300]

    return score, reasoning


# ── Scoring prompt ────────────────────────────────────────────────────────────

SCORE_PROMPT = """You are a job fit evaluator. Score how well this job matches the candidate.

CANDIDATE RESUME:
{resume}

JOB PREFERENCES:
{preferences}

JOB TO EVALUATE:
Title: {title}
Company: {company}
Location: {location}
Remote: {is_remote}
Description: {description}

Evaluate fit on these criteria:
1. Title matches target roles (data analyst, BI analyst, python developer, analytics engineer)
2. Required experience level is entry to junior (0-3 years), NOT senior or principal
3. Skills match (Python, SQL, data analysis, pandas, Power BI, Tableau, etc.)
4. Location works (Houston TX, Seattle WA, or remote)
5. No hard nos (no SAP admin, no commission-only, no 5+ years required)

Respond in EXACTLY this format, nothing else:
SCORE: [1-10]
REASONING: [one sentence explaining the score]"""


# ── Core scorer ───────────────────────────────────────────────────────────────

def score_job(job: dict, resume: str, prefs: str, cfg: dict) -> tuple[int, str]:
    model = cfg["model"]["name"]
    prompt = SCORE_PROMPT.format(
        resume=resume,
        preferences=prefs,
        title=job.get("title", ""),
        company=job.get("company", ""),
        location=job.get("location", ""),
        is_remote=job.get("is_remote", False),
        description=job.get("description", "")[:1500],
    )

    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},  # low temp for consistent scoring
        )
        text = response["message"]["content"]
        return parse_score(text)
    except Exception as e:
        log.error(f"Scoring failed for {job.get('title')} @ {job.get('company')}: {e}")
        return 0, f"Error: {e}"


def run_scorer() -> dict:
    cfg    = load_config()
    resume = load_resume_text()
    prefs  = load_preferences_text()
    apps   = load_applications()

    auto_threshold   = cfg["scoring"]["auto_apply_threshold"]
    review_threshold = cfg["scoring"]["review_threshold"]

    # Only score jobs not yet scored
    to_score = [j for j in apps if j.get("score") is None and j.get("status") == "scraped"]
    log.info(f"Jobs to score: {len(to_score)}")

    results = {"auto": [], "review": [], "skip": []}

    for i, job in enumerate(to_score):
        log.info(f"[{i+1}/{len(to_score)}] Scoring: {job['title']} @ {job['company']}")

        score, reasoning = score_job(job, resume, prefs, cfg)

        # Update job record in place
        job["score"]     = score
        job["reasoning"] = reasoning

        if score >= auto_threshold:
            job["status"] = "auto_apply"
            results["auto"].append(job)
            log.info(f"  Score {score}/10 -> AUTO APPLY  | {reasoning}")
            # Quick ATS scan for auto-apply jobs — stores score for dashboard/notifier
            ats = ats_scan_job(job, model=cfg["model"]["name"], resume=resume, quick=True)
            if "error" not in ats:
                job["ats_score"]          = ats.get("ats_score")
                job["ats_score_reasoning"] = ats.get("score_reasoning")
                log.info(f"  ATS score: {job['ats_score']}/100 | {job['ats_score_reasoning']}")
        elif score >= review_threshold:
            job["status"] = "needs_review"
            results["review"].append(job)
            log.info(f"  Score {score}/10 -> NEEDS REVIEW | {reasoning}")
        else:
            job["status"] = "skipped"
            results["skip"].append(job)
            log.info(f"  Score {score}/10 -> SKIPPED      | {reasoning}")

        # Small delay to avoid hammering Ollama
        time.sleep(0.5)

    save_applications(apps)

    log.info(
        f"\nScoring complete — "
        f"Auto: {len(results['auto'])} | "
        f"Review: {len(results['review'])} | "
        f"Skipped: {len(results['skip'])}"
    )
    return results


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = run_scorer()

    print(f"\n{'='*50}")
    print(f"SCORING SUMMARY")
    print(f"{'='*50}")

    if results["auto"]:
        print(f"\n✓ AUTO APPLY ({len(results['auto'])} jobs):")
        for j in results["auto"]:
            print(f"  [{j['score']}/10] {j['title']} @ {j['company']} — {j['location']}")

    if results["review"]:
        print(f"\n? NEEDS YOUR REVIEW ({len(results['review'])} jobs):")
        for j in results["review"]:
            print(f"  [{j['score']}/10] {j['title']} @ {j['company']} — {j['location']}")
            print(f"         {j['reasoning']}")

    if results["skip"]:
        print(f"\n✗ SKIPPED ({len(results['skip'])} jobs — low fit)")
