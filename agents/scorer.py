import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

import httpx
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
PROMPT_PATH  = BASE_DIR / "config" / "scoring_prompt.md"


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
    # Cap generously — preferences.md is ~5KB and the good/bad keyword
    # sections near the end MUST reach the LLM (they drive hard rejects).
    if not PREFS.exists():
        return ""
    return PREFS.read_text(encoding="utf-8")[:8000]


def load_applications() -> list[dict]:
    if not APPS_PATH.exists():
        return []
    with open(APPS_PATH) as f:
        return json.load(f)


def save_applications(apps: list[dict]) -> None:
    with open(APPS_PATH, "w") as f:
        json.dump(apps, f, indent=2)


def _load_prompt_template() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Scoring prompt not found: {PROMPT_PATH}")


def parse_score(response: str) -> dict:
    """Extract all scored fields from model response."""
    def _int(pattern: str) -> int:
        m = re.search(pattern, response, re.IGNORECASE)
        try:
            return max(1, min(10, int(m.group(1)))) if m else 0
        except (ValueError, AttributeError):
            return 0

    def _str(pattern: str, fallback: str = "") -> str:
        m = re.search(pattern, response, re.IGNORECASE)
        return m.group(1).strip() if m else fallback

    score        = _int(r"SCORE:\s*([0-9]|10)")
    tech_match   = _int(r"TECH_MATCH:\s*([0-9]|10)")
    seniority    = _int(r"SENIORITY_FIT:\s*([0-9]|10)")
    archetype    = _str(r"ARCHETYPE:\s*([^\n]+)")
    reasoning_raw = _str(r"REASONING:\s*([^\n]+)", response[:300])
    reasoning    = reasoning_raw[:500]

    gaps_raw = _str(r"GAPS:\s*([^\n]+)")
    if gaps_raw.lower() in ("none", ""):
        gaps: list[str] = []
    else:
        gaps = [g.strip() for g in gaps_raw.split("|") if g.strip()]

    return {
        "score":        score,
        "reasoning":    reasoning,
        "archetype":    archetype,
        "tech_match":   tech_match,
        "seniority_fit": seniority,
        "gaps":         gaps,
    }


# ── Core scorer ───────────────────────────────────────────────────────────────

def score_job(job: dict, resume: str, prefs: str, cfg: dict) -> dict:
    model          = cfg["model"]["name"]
    auto_threshold = cfg["scoring"]["auto_apply_threshold"]
    think_mode     = cfg["model"].get("think_mode", False)

    template = _load_prompt_template()
    prompt   = template.format(
        resume=resume,
        preferences=prefs,
        title=job.get("title", ""),
        company=job.get("company", ""),
        location=job.get("location", ""),
        is_remote=job.get("is_remote", False),
        description=job.get("description", "")[:1500],
        auto_threshold=auto_threshold,
    )

    def _call():
        client = ollama.Client(timeout=httpx.Timeout(connect=10, read=90, write=10, pool=10))
        resp   = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "think": think_mode},
        )
        return resp["message"]["content"]

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_call)
        text   = future.result(timeout=120)
        return parse_score(text)
    except FuturesTimeoutError:
        log.error(f"Scoring timed out for {job.get('title')} @ {job.get('company')}")
        return {"score": 0, "reasoning": "Error: timed out", "archetype": "", "tech_match": 0, "seniority_fit": 0, "gaps": []}
    except Exception as e:
        log.error(f"Scoring failed for {job.get('title')} @ {job.get('company')}: {e}")
        return {"score": 0, "reasoning": f"Error: {e}", "archetype": "", "tech_match": 0, "seniority_fit": 0, "gaps": []}
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def run_scorer() -> dict:
    cfg    = load_config()
    resume = load_resume_text()
    prefs  = load_preferences_text()
    apps   = load_applications()

    auto_threshold = cfg["scoring"]["auto_apply_threshold"]

    # Only score jobs not yet scored
    to_score = [j for j in apps if j.get("score") is None and j.get("status") == "scraped"]
    log.info(f"Jobs to score: {len(to_score)}")

    results = {"auto": [], "rejected": []}

    for i, job in enumerate(to_score):
        log.info(f"[{i+1}/{len(to_score)}] Scoring: {job['title']} @ {job['company']}")

        result = score_job(job, resume, prefs, cfg)
        score  = result["score"]

        job["score"]         = score
        job["reasoning"]     = result["reasoning"]
        job["archetype"]     = result["archetype"]
        job["score_breakdown"] = {
            "tech_match":    result["tech_match"],
            "seniority_fit": result["seniority_fit"],
        }
        job["gaps"] = result["gaps"]

        if score >= auto_threshold:
            job["status"] = "auto_apply"
            results["auto"].append(job)
            log.info(f"  {score}/10 [{result['archetype']}] -> AUTO APPLY | {result['reasoning']}")
        else:
            job["status"] = "rejected"
            results["rejected"].append(job)
            log.info(f"  {score}/10 [{result['archetype']}] -> REJECTED   | {result['reasoning']}")

        time.sleep(0.5)

        if (i + 1) % 10 == 0:
            save_applications(apps)
            log.info(f"  [checkpoint] saved at {i+1}/{len(to_score)}")

    save_applications(apps)

    log.info(
        f"\nScoring complete - "
        f"Auto: {len(results['auto'])} | "
        f"Rejected: {len(results['rejected'])}"
    )
    return results


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = run_scorer()

    print(f"\n{'='*50}")
    print("SCORING SUMMARY")
    print(f"{'='*50}")

    if results["auto"]:
        print(f"\n[AUTO APPLY] ({len(results['auto'])} jobs):")
        for j in results["auto"]:
            print(f"  [{j['score']}/10] {j['title']} @ {j['company']} - {j['location']}")

    if results["rejected"]:
        print(f"\n[REJECTED] ({len(results['rejected'])} jobs - low fit)")
