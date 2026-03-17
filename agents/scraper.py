import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv
from jobspy import scrape_jobs

# ── Setup ────────────────────────────────────────────────────────────────────

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
SEEN_PATH = BASE_DIR / "data" / "seen_jobs.json"
APPS_PATH = BASE_DIR / "data" / "applications.json"
PREFS     = BASE_DIR / "profile" / "preferences.md"


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG) as f:
        return yaml.safe_load(f)


def load_seen_jobs() -> set:
    if SEEN_PATH.exists():
        with open(SEEN_PATH) as f:
            return set(json.load(f))
    return set()


def save_seen_jobs(seen: set) -> None:
    with open(SEEN_PATH, "w") as f:
        json.dump(list(seen), f, indent=2)


def load_preferences() -> dict:
    """Parse preferences.md into a usable dict for filtering."""
    prefs = {
        "roles": [],
        "locations": [],
        "bad_keywords": [],
        "good_keywords": [],
    }
    if not PREFS.exists():
        log.warning("preferences.md not found — using defaults")
        return prefs

    section = None
    with open(PREFS) as f:
        for line in f:
            line = line.strip()
            if line.startswith("## Target roles"):
                section = "roles"
            elif line.startswith("## Target locations"):
                section = "locations"
            elif line.startswith("## Keywords that signal a GOOD fit"):
                section = "good"
            elif line.startswith("## Keywords that signal a BAD fit"):
                section = "bad"
            elif line.startswith("##"):
                section = None
            elif line.startswith("- ") and section == "roles":
                prefs["roles"].append(line[2:].strip().lower())
            elif line.startswith("- ") and section == "locations":
                prefs["locations"].append(line[2:].strip())
            elif section == "good" and line and not line.startswith("#"):
                prefs["good_keywords"].extend(
                    [k.strip().lower() for k in line.split(",") if k.strip()]
                )
            elif section == "bad" and line and not line.startswith("#"):
                prefs["bad_keywords"].extend(
                    [k.strip().lower() for k in line.split(",") if k.strip()]
                )
    return prefs


def make_job_id(job: pd.Series) -> str:
    """Stable ID from title + company + location."""
    raw = f"{job.get('title','')}|{job.get('company','')}|{job.get('location','')}".lower()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def is_hard_no(job: pd.Series, prefs: dict) -> bool:
    """Return True if any bad keyword appears in title or description."""
    text = " ".join([
        str(job.get("title", "")),
        str(job.get("description", "")),
    ]).lower()
    for kw in prefs["bad_keywords"]:
        if kw and kw in text:
            log.info(f"  Filtered (bad keyword '{kw}'): {job.get('title')} @ {job.get('company')}")
            return True
    return False


# ── Core scrape ──────────────────────────────────────────────────────────────

def run_scraper() -> list[dict]:
    cfg   = load_config()
    prefs = load_preferences()
    seen  = load_seen_jobs()

    search_terms = cfg.get("scraper", {}).get("search_terms", ["data analyst"])
    locations    = cfg.get("scraper", {}).get("locations", ["Houston, TX"])
    hours_old    = cfg.get("scraper", {}).get("hours_old", 72)
    results_each = cfg.get("scraper", {}).get("results_per_search", 25)
    sites        = cfg.get("scraper", {}).get("sites", ["indeed", "linkedin"])

    all_new: list[dict] = []
    run_seen = set()        # ← add this line

    for term in search_terms:
        for location in locations:
            log.info(f"Scraping: '{term}' in '{location}'")
            try:
                df = scrape_jobs(
                    site_name=sites,
                    search_term=term,
                    location=location,
                    results_wanted=results_each,
                    hours_old=hours_old,
                    country_indeed="USA",
                    linkedin_fetch_description=True,
                    is_remote=cfg.get("scraper", {}).get("is_remote", False),
                )
            except Exception as e:
                log.error(f"Scrape failed for '{term}' in '{location}': {e}")
                continue

            log.info(f"  Raw results: {len(df)}")

            for _, job in df.iterrows():
                job_id = make_job_id(job)

                # Skip already seen
                if job_id in seen:
                    continue

                # Secondary dedup by title+company within this run
                run_key = f"{job.get('title','').lower()}|{job.get('company','').lower()}"
                if run_key in run_seen:
                    seen.add(job_id)
                    continue
                run_seen.add(run_key)

                # Skip hard nos immediately
                if is_hard_no(job, prefs):
                    seen.add(job_id)
                    continue

                record = {
                    "id":          job_id,
                    "title":       str(job.get("title", "")).strip(),
                    "company":     str(job.get("company", "")).strip(),
                    "location":    str(job.get("location", "")).strip(),
                    "job_url":     str(job.get("job_url", "")),
                    "site":        str(job.get("site", "")),
                    "description": str(job.get("description", ""))[:3000],  # cap length
                    "date_posted": str(job.get("date_posted", "")),
                    "salary_min":  str(job.get("min_amount", "")),
                    "salary_max":  str(job.get("max_amount", "")),
                    "is_remote":   bool(job.get("is_remote", False)),
                    "scraped_at":  datetime.utcnow().isoformat(),
                    "status":      "scraped",
                    "score":       None,
                    "applied_at":  None,
                }

                seen.add(job_id)
                all_new.append(record)
                log.info(f"  New job: {record['title']} @ {record['company']}")

    save_seen_jobs(seen)
    log.info(f"Scrape complete — {len(all_new)} new jobs found")
    return all_new


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    jobs = run_scraper()

    if not jobs:
        log.info("No new jobs this run.")
    else:
        # Save to data/applications.json for scorer to pick up
        existing = []
        if APPS_PATH.exists():
            with open(APPS_PATH) as f:
                existing = json.load(f)

        existing.extend(jobs)

        with open(APPS_PATH, "w") as f:
            json.dump(existing, f, indent=2)

        log.info(f"Saved {len(jobs)} new jobs to data/applications.json")
        print(f"\n✓ {len(jobs)} new jobs ready for scoring.")
