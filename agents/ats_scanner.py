"""
agents/ats_scanner.py

Per-job ATS analysis agent.
Compares resume against a specific job posting and returns:
- ATS match score (0-100)
- Missing keywords
- Present keywords
- Weak bullet points with rewrites
- Skills section issues
- Recommended resume tweaks

Called by the dashboard and applicator per job.
"""

import json
import logging
import re
from pathlib import Path

import ollama
import yaml

# ── Setup ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
CONFIG   = BASE_DIR / "config" / "settings.yaml"
RESUME   = BASE_DIR / "profile" / "resume.tex"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG) as f:
        return yaml.safe_load(f)


def load_resume_text() -> str:
    if not RESUME.exists():
        return ""
    raw = RESUME.read_text(encoding="utf-8")
    raw = re.sub(r"\\[a-zA-Z]+\*?(\[.*?\])?\{(.*?)\}", r"\2", raw)
    raw = re.sub(r"\\[a-zA-Z]+", " ", raw)
    raw = re.sub(r"[{}]", " ", raw)
    raw = re.sub(r"%.*", "", raw)
    return re.sub(r"\s+", " ", raw).strip()[:3000]


# ── Prompt ────────────────────────────────────────────────────────────────────

ATS_PROMPT_QUICK = """You are an ATS analyst. Score how well this resume matches the job posting.

RESUME:
{resume}

JOB POSTING:
Title: {title}
Company: {company}
Description: {description}

Respond in EXACTLY this JSON format, nothing else:
{{
  "ats_score": <integer 0-100>,
  "score_reasoning": "<one sentence explaining the score>"
}}

ATS score: 90-100 = strong match, 70-89 = good, 50-69 = moderate, below 50 = poor fit.
Output valid JSON only, no markdown fences, no preamble."""


ATS_PROMPT = """You are an expert ATS (Applicant Tracking System) analyst and resume coach.
Analyze how well this resume matches the job posting.

RESUME:
{resume}

JOB POSTING:
Title: {title}
Company: {company}
Description: {description}

Provide a detailed analysis in EXACTLY this JSON format, nothing else:
{{
  "ats_score": <integer 0-100>,
  "score_reasoning": "<one sentence explaining the score>",
  "missing_keywords": [
    {{"keyword": "<term>", "importance": "<high|medium|low>", "where_to_add": "<specific suggestion>"}}
  ],
  "present_keywords": ["<keyword1>", "<keyword2>"],
  "weak_bullets": [
    {{
      "original": "<exact bullet text from resume>",
      "issue": "<what's weak about it>",
      "rewrite": "<improved version>"
    }}
  ],
  "skills_issues": [
    {{"issue": "<problem>", "fix": "<solution>"}}
  ],
  "quick_wins": ["<actionable change 1>", "<actionable change 2>", "<actionable change 3>"],
  "overall_verdict": "<2-3 sentence honest assessment>"
}}

Rules:
- Be brutally honest — this person needs real feedback not flattery
- Only flag weak bullets that are genuinely weak for THIS specific job
- Missing keywords must actually appear in the job description
- Quick wins should be achievable in under 10 minutes
- ATS score: 90-100 = strong match, 70-89 = good, 50-69 = moderate, below 50 = poor fit
- Output valid JSON only, no markdown fences, no preamble"""


# ── Core scanner ──────────────────────────────────────────────────────────────

def scan_job(job: dict, model: str = None, resume: str = None, quick: bool = False) -> dict:
    """
    Run ATS analysis for a single job.
    quick=True returns only ats_score + score_reasoning (fast).
    quick=False returns the full analysis with keywords, bullets, etc.
    """
    if model is None or resume is None:
        cfg    = load_config()
        model  = model or cfg["model"]["name"]
        resume = resume or load_resume_text()

    template = ATS_PROMPT_QUICK if quick else ATS_PROMPT
    prompt = template.format(
        resume=resume,
        title=job.get("title", ""),
        company=job.get("company", ""),
        description=job.get("description", "")[:2500],
    )

    log.info(f"ATS scan: {job.get('title')} @ {job.get('company')}")

    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
        )
        raw = response["message"]["content"].strip()

        # Strip markdown fences if model added them anyway
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"^```\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

        result = json.loads(raw)
        log.info(f"  ATS score: {result.get('ats_score')}/100")
        return result

    except json.JSONDecodeError as e:
        log.error(f"ATS scan JSON parse failed: {e}")
        return {"error": f"JSON parse failed: {e}", "raw": raw}
    except Exception as e:
        log.error(f"ATS scan failed: {e}")
        return {"error": str(e)}


def scan_multiple(jobs: list[dict]) -> dict[str, dict]:
    """Scan multiple jobs, keyed by job ID."""
    cfg    = load_config()
    model  = cfg["model"]["name"]
    resume = load_resume_text()
    results = {}
    for job in jobs:
        results[job["id"]] = scan_job(job, model=model, resume=resume)
    return results


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from agents.scraper import load_seen_jobs
    from agents.scorer  import load_applications

    apps  = load_applications()
    queue = [a for a in apps if a.get("status") == "auto_apply" and not a.get("applied_at")]

    if not queue:
        print("No jobs in apply queue.")
        sys.exit(0)

    print(f"Scanning {min(3, len(queue))} jobs from your apply queue...\n")

    cfg    = load_config()
    model  = cfg["model"]["name"]
    resume = load_resume_text()

    for job in queue[:3]:
        result = scan_job(job, model=model, resume=resume)

        if "error" in result:
            print(f"ERROR: {result['error']}")
            continue

        score = result.get("ats_score", 0)
        bar   = "█" * (score // 10) + "░" * (10 - score // 10)

        print(f"{'='*60}")
        print(f"{job['title']} @ {job['company']}")
        print(f"ATS Score: {score}/100  [{bar}]")
        print(f"  {result.get('score_reasoning','')}")
        print()

        missing = result.get("missing_keywords", [])
        high    = [k for k in missing if k.get("importance") == "high"]
        if high:
            print(f"HIGH PRIORITY missing keywords:")
            for k in high:
                print(f"  → {k['keyword']}  |  Add to: {k['where_to_add']}")
            print()

        present = result.get("present_keywords", [])
        if present:
            print(f"Already covered: {', '.join(present[:8])}")
            print()

        weak = result.get("weak_bullets", [])
        if weak:
            print(f"Weak bullets to fix:")
            for b in weak[:2]:
                print(f"  Before: {b['original'][:80]}")
                print(f"  After:  {b['rewrite'][:80]}")
                print()

        wins = result.get("quick_wins", [])
        if wins:
            print(f"Quick wins (under 10 min):")
            for w in wins:
                print(f"  • {w}")
            print()

        print(f"Verdict: {result.get('overall_verdict','')}")
        print()
