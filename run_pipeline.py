"""
run_pipeline.py

Master pipeline — run manually or via Windows Task Scheduler at 9 AM.
Chains: scraper → scorer → notifier → daily briefing (Discord)
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent
(ROOT / "logs").mkdir(exist_ok=True)
(ROOT / "data").mkdir(exist_ok=True)

APPS_PATH = ROOT / "data" / "applications.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(ROOT / "logs" / "agent.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ── Pipeline ──────────────────────────────────────────────────────────────────

def main() -> None:
    start = datetime.now()
    log.info(f"{'='*50}")
    log.info(f"Pipeline started: {start.strftime('%Y-%m-%d %H:%M')}")
    log.info(f"{'='*50}")

    # ── Step 1: Scrape (jobspy + portal APIs in parallel) ─────────────────
    log.info("STEP 1 — Scraping job listings...")
    import concurrent.futures as _cf
    from agents.scraper import run_scraper
    from agents.portal_scanner import run_portal_scanner

    scraper_jobs: list[dict] = []
    portal_jobs:  list[dict] = []

    def _run_scraper():
        try:
            return run_scraper()
        except Exception as e:
            log.error(f"Scraper failed: {e}")
            raise

    def _run_portals():
        try:
            return run_portal_scanner()
        except Exception as e:
            log.warning(f"Portal scanner failed (non-fatal): {e}")
            return []

    with _cf.ThreadPoolExecutor(max_workers=2) as pool:
        f_scraper = pool.submit(_run_scraper)
        f_portals = pool.submit(_run_portals)

        try:
            scraper_jobs = f_scraper.result()
        except Exception:
            sys.exit(1)

        portal_jobs = f_portals.result()

    new_jobs = scraper_jobs + portal_jobs
    log.info(
        f"Step 1 complete — {len(scraper_jobs)} from jobspy, "
        f"{len(portal_jobs)} from portals, {len(new_jobs)} total"
    )

    if not new_jobs:
        log.info("No new jobs found — pipeline complete.")
        elapsed = int((datetime.now() - start).total_seconds())
        _send_daily_briefing([], 0, 0, elapsed)
        return

    # ── Step 2: Score ─────────────────────────────────
    log.info("STEP 2 — Scoring jobs...")
    try:
        from agents.scorer import run_scorer
        results  = run_scorer()
        auto     = len(results["auto"])
        rejected = len(results["rejected"])
        log.info(f"Scorer complete — Auto: {auto} | Rejected: {rejected}")
    except Exception as e:
        log.error(f"Scorer failed: {e}")
        sys.exit(1)

    # ── Summary + Briefing ────────────────────────────
    elapsed = int((datetime.now() - start).total_seconds())
    log.info(f"{'='*50}")
    log.info(f"Pipeline complete in {elapsed}s")
    log.info(f"  New jobs scraped: {len(new_jobs)}")
    log.info(f"  Auto-apply queue: {auto}")
    log.info(f"  Rejected:         {rejected}")
    log.info(f"{'='*50}")

    # Compute score distribution and site breakdown for briefing
    score_dist = {s: sum(1 for j in new_jobs if j.get("score") == s) for s in range(7, 11)}
    site_counts: dict[str, int] = {}
    for j in new_jobs:
        # Group all portal sources under "portals" for a cleaner briefing line
        site = j.get("site", "unknown")
        if site in ("greenhouse", "ashby", "lever"):
            site = "portals"
        site_counts[site] = site_counts.get(site, 0) + 1

    _send_daily_briefing(new_jobs, auto, rejected, elapsed, score_dist, site_counts)


def _send_daily_briefing(
    new_jobs: list[dict],
    auto: int,
    rejected: int,
    elapsed: int,
    score_dist: dict[int, int] | None = None,
    site_counts: dict[str, int] | None = None,
) -> None:
    """Send a rich daily briefing embed to Discord."""
    import os
    import asyncio
    import discord
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")

    token      = os.getenv("DISCORD_BOT_TOKEN")
    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if not token or not channel_id:
        log.warning("Discord credentials missing — skipping briefing")
        return

    # Cumulative stats from applications.json
    all_apps = []
    if APPS_PATH.exists():
        try:
            with open(APPS_PATH) as f:
                all_apps = json.load(f)
        except Exception:
            pass

    total_applied = sum(1 for j in all_apps if j.get("status") == "applied")
    total_queue   = sum(1 for j in all_apps if j.get("status") == "auto_apply")

    # Build embed
    today = datetime.now().strftime("%B %d, %Y")

    if new_jobs:
        color = discord.Color.green() if auto > 0 else discord.Color.gold()
        desc = f"Pipeline completed in {elapsed}s — **{len(new_jobs)}** new jobs found"
    else:
        color = discord.Color.light_grey()
        desc = f"Pipeline completed in {elapsed}s — no new jobs today"

    embed = discord.Embed(
        title=f"Daily Briefing — {today}",
        description=desc,
        color=color,
        timestamp=datetime.utcnow(),
    )

    # This run
    embed.add_field(name="New Jobs",   value=str(len(new_jobs)), inline=True)
    embed.add_field(name="Auto-Apply", value=str(auto),          inline=True)
    embed.add_field(name="Rejected",   value=str(rejected),      inline=True)

    # Score distribution
    if score_dist:
        dist_str = "  ".join(
            f"{s}★ {n}" for s, n in sorted(score_dist.items()) if n > 0
        ) or "none"
        embed.add_field(name="Score Dist.", value=dist_str, inline=False)

    # Site breakdown
    if site_counts:
        site_str = "  ·  ".join(
            f"{site.replace('_', ' ').title()}: {n}"
            for site, n in sorted(site_counts.items(), key=lambda x: -x[1])
        )
        embed.add_field(name="By Site", value=site_str, inline=False)

    # Cumulative
    embed.add_field(name="Total Applied",      value=str(total_applied), inline=True)
    embed.add_field(name="Pending Auto-Apply", value=str(total_queue),   inline=True)

    async def _notify():
        intents = discord.Intents.default()
        client  = discord.Client(intents=intents)

        @client.event
        async def on_ready():
            ch = client.get_channel(channel_id)
            if ch:
                await ch.send(embed=embed)
            await client.close()

        await client.start(token)

    try:
        asyncio.run(_notify())
        log.info("Daily briefing sent to Discord")
    except Exception as e:
        log.error(f"Failed to send daily briefing: {e}")


if __name__ == "__main__":
    main()
