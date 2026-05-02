"""
portal_scanner.py — Zero-LLM portal scanner.

Hits Greenhouse, Ashby, and Lever APIs directly, filters by title keywords
from config/portals.yml, deduplicates against seen_jobs.json, and writes
new jobs to applications.json in the same format as scraper.py.
"""

import json
import logging
import re
import uuid
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

BASE_DIR       = Path(__file__).parent.parent
APPS_PATH      = BASE_DIR / "data" / "applications.json"
PORTALS_PATH   = BASE_DIR / "config" / "portals.yml"
SEEN_JOBS_PATH = BASE_DIR / "data" / "seen_jobs.json"

FETCH_TIMEOUT = 10
MAX_WORKERS   = 10

log = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────────────────

def _load_portals() -> dict:
    with open(PORTALS_PATH) as f:
        return yaml.safe_load(f)


def _load_seen() -> set[str]:
    if SEEN_JOBS_PATH.exists():
        return set(json.loads(SEEN_JOBS_PATH.read_text()))
    return set()


def _load_existing_ids() -> set[str]:
    if APPS_PATH.exists():
        apps = json.loads(APPS_PATH.read_text())
        return {a["id"] for a in apps if "id" in a}
    return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_JOBS_PATH.write_text(json.dumps(sorted(seen), indent=2))


def _make_job_id(title: str, company: str, location: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{title}|{company}|{location}"))


# ── API detection ───────────────────────────────────────────────────────────

def _detect_api(company: dict) -> dict | None:
    # Explicit api field takes priority
    if explicit := company.get("api", ""):
        if "greenhouse" in explicit:
            return {"type": "greenhouse", "url": explicit}
        if "ashby" in explicit:
            return {"type": "ashby", "url": explicit}
        if "lever" in explicit:
            return {"type": "lever", "url": explicit}

    url = company.get("careers_url", "")

    if m := re.search(r"jobs\.ashbyhq\.com/([^/?#]+)", url):
        slug = m.group(1)
        return {
            "type": "ashby",
            "url": f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
        }

    if m := re.search(r"jobs\.lever\.co/([^/?#]+)", url):
        return {"type": "lever", "url": f"https://api.lever.co/v0/postings/{m.group(1)}"}

    if m := re.search(r"job-boards(?:\.eu)?\.greenhouse\.io/([^/?#]+)", url):
        return {"type": "greenhouse", "url": f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs"}

    return None


# ── API parsers ─────────────────────────────────────────────────────────────

def _parse_greenhouse(data: dict, company: str) -> list[dict]:
    out = []
    for j in data.get("jobs", []):
        out.append({
            "title":       j.get("title", ""),
            "url":         j.get("absolute_url", ""),
            "company":     company,
            "location":    (j.get("location") or {}).get("name", ""),
            "description": "",
            "salary_min":  "nan",
            "salary_max":  "nan",
            "is_remote":   False,
            "date_posted": "",
            "source":      "greenhouse",
        })
    return out


def _parse_ashby(data: dict, company: str) -> list[dict]:
    out = []
    for j in data.get("jobs", []):
        comp    = j.get("compensation") or {}
        min_sal = str(comp.get("minValue", "nan"))
        max_sal = str(comp.get("maxValue", "nan"))
        out.append({
            "title":       j.get("title", ""),
            "url":         j.get("jobUrl", ""),
            "company":     company,
            "location":    j.get("location", ""),
            "description": (j.get("descriptionPlain") or "")[:3000],
            "salary_min":  min_sal,
            "salary_max":  max_sal,
            "is_remote":   bool(j.get("isRemote", False)),
            "date_posted": (j.get("publishedAt") or "")[:10],
            "source":      "ashby",
        })
    return out


def _parse_lever(data: list, company: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        cats = j.get("categories") or {}
        out.append({
            "title":       j.get("text", ""),
            "url":         j.get("hostedUrl", ""),
            "company":     company,
            "location":    cats.get("location", ""),
            "description": (j.get("descriptionPlain") or "")[:3000],
            "salary_min":  "nan",
            "salary_max":  "nan",
            "is_remote":   False,
            "date_posted": "",
            "source":      "lever",
        })
    return out


_PARSERS = {
    "greenhouse": _parse_greenhouse,
    "ashby":      _parse_ashby,
    "lever":      _parse_lever,
}


# ── Title filter ────────────────────────────────────────────────────────────

def _title_passes(title: str, positive: list[str], negative: list[str]) -> bool:
    lower = title.lower()
    if positive and not any(k.lower() in lower for k in positive):
        return False
    if any(k.lower() in lower for k in negative):
        return False
    return True


# ── Fetch ───────────────────────────────────────────────────────────────────

def _fetch_json(url: str) -> dict | list:
    resp = requests.get(
        url,
        timeout=FETCH_TIMEOUT,
        headers={"User-Agent": "OpenClaw/1.0"},
    )
    resp.raise_for_status()
    return resp.json()


# ── Main ────────────────────────────────────────────────────────────────────

def run_portal_scanner(dry_run: bool = False) -> list[dict]:
    """
    Scan all enabled companies in config/portals.yml.
    Returns list of new job dicts (same shape as run_scraper output).
    Writes results to applications.json and updates seen_jobs.json unless dry_run.
    """
    if not PORTALS_PATH.exists():
        log.warning("config/portals.yml not found — skipping portal scan")
        return []

    config   = _load_portals()
    positive = [k.lower() for k in config.get("title_filter", {}).get("positive", [])]
    negative = [k.lower() for k in config.get("title_filter", {}).get("negative", [])]

    companies = config.get("tracked_companies", [])
    targets   = []
    for c in companies:
        if c.get("enabled", True) is False:
            continue
        api = _detect_api(c)
        if api:
            targets.append({**c, "_api": api})
        else:
            log.debug(f"No supported API for {c.get('name')} — skipped")

    log.info(f"Portal scanner: scanning {len(targets)} companies "
             f"({len(companies) - len(targets)} skipped — no API detected)")

    seen_ids     = _load_seen()
    existing_ids = _load_existing_ids()
    all_seen     = seen_ids | existing_ids
    intra_keys: set[str] = set()

    now      = datetime.now(timezone.utc).isoformat()
    new_jobs: list[dict] = []
    errors:   list[dict] = []

    def _scan_one(target: dict) -> list[dict]:
        api          = target["_api"]
        company_name = target["name"]
        results      = []
        try:
            data     = _fetch_json(api["url"])
            raw_jobs = _PARSERS[api["type"]](data, company_name)
        except Exception as exc:
            errors.append({"company": company_name, "error": str(exc)})
            return []

        for j in raw_jobs:
            if not j["title"] or not j["url"]:
                continue
            if not _title_passes(j["title"], positive, negative):
                continue

            job_id    = _make_job_id(j["title"], j["company"], j["location"])
            intra_key = f"{j['company'].lower()}::{j['title'].lower()}"

            if job_id in all_seen or intra_key in intra_keys:
                continue

            all_seen.add(job_id)
            intra_keys.add(intra_key)

            results.append({
                "id":             job_id,
                "title":          j["title"],
                "company":        j["company"],
                "location":       j["location"],
                "job_url":        j["url"],
                "job_url_direct": j["url"],
                "site":           j["source"],
                "description":    j.get("description", ""),
                "date_posted":    j.get("date_posted", ""),
                "salary_min":     j.get("salary_min", "nan"),
                "salary_max":     j.get("salary_max", "nan"),
                "is_remote":      j.get("is_remote", False),
                "scraped_at":     now,
                "search_group":   "portal_scan",
                "status":         "scraped",
                "score":          None,
                "applied_at":     None,
            })
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for result in pool.map(_scan_one, targets):
            new_jobs.extend(result)

    for e in errors:
        log.warning(f"Portal scan error — {e['company']}: {e['error']}")

    log.info(f"Portal scan complete: {len(new_jobs)} new jobs")

    if dry_run or not new_jobs:
        return new_jobs

    # Persist to applications.json
    apps = json.loads(APPS_PATH.read_text()) if APPS_PATH.exists() else []
    apps.extend(new_jobs)
    APPS_PATH.write_text(json.dumps(apps, indent=2))

    # Update seen_jobs.json with new IDs
    new_ids = {j["id"] for j in new_jobs}
    _save_seen(seen_ids | new_ids)

    from lib.pipeline_log import append_jobs
    append_jobs(new_jobs)

    return new_jobs


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    dry = "--dry-run" in sys.argv
    jobs = run_portal_scanner(dry_run=dry)
    print(f"\nFound {len(jobs)} new jobs")
    for j in jobs:
        print(f"  {j['company']} | {j['title']} | {j['location']}")
