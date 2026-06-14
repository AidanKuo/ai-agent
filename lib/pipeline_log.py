"""
pipeline_log.py — Append new jobs to data/pipeline.md.

Called by scraper.py and portal_scanner.py after each run so there is a
human-readable log of every job that entered the pipeline, separate from
the large applications.json database.

Format:
    | Date       | Source       | Company       | Role             | Location    | ID       |
"""

from datetime import datetime, timezone
from pathlib import Path

BASE_DIR     = Path(__file__).parent.parent
PIPELINE_MD  = BASE_DIR / "data" / "pipeline.md"

_HEADER = """\
# Pipeline Log

Appended by scraper and portal scanner on each run.
Each row is a job that entered `data/applications.json` for scoring.

| Date | Source | Company | Role | Location | Remote | ID |
|------|--------|---------|------|----------|--------|----|
"""


def append_jobs(jobs: list[dict]) -> None:
    """Append a list of new job records to data/pipeline.md."""
    if not jobs:
        return

    PIPELINE_MD.parent.mkdir(parents=True, exist_ok=True)

    if not PIPELINE_MD.exists():
        PIPELINE_MD.write_text(_HEADER, encoding="utf-8")

    lines = []
    for job in jobs:
        date     = (job.get("scraped_at") or datetime.now(timezone.utc).isoformat())[:10]
        source   = _clean(job.get("site") or job.get("search_group") or "unknown")
        company  = _clean(job.get("company", "—"))
        role     = _clean(job.get("title", "—"))
        location = _clean(job.get("location", "—"))
        remote   = "Yes" if job.get("is_remote") else "No"
        job_id   = str(job.get("id", ""))[:8]
        lines.append(f"| {date} | {source} | {company} | {role} | {location} | {remote} | {job_id} |")

    with PIPELINE_MD.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _clean(text: str) -> str:
    """Strip pipe characters so they don't break the markdown table."""
    return str(text).replace("|", "/").replace("\n", " ").strip()[:50]
