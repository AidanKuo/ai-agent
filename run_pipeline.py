"""
run_pipeline.py

Master pipeline — runs every morning via Windows Task Scheduler.
Chains: scraper → scorer → notifier (Discord)

After this script runs, check Discord then review jobs in the dashboard (localhost:8501).
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────────────────────────

Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent.log"),
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

    # ── Step 1: Scrape ────────────────────────────────
    log.info("STEP 1 — Scraping job listings...")
    try:
        from agents.scraper import run_scraper
        new_jobs = run_scraper()
        log.info(f"Scraper complete — {len(new_jobs)} new jobs")
    except Exception as e:
        log.error(f"Scraper failed: {e}")
        sys.exit(1)

    if not new_jobs:
        log.info("No new jobs found — pipeline complete.")
        _send_discord_summary(0, 0, 0)
        return

    # ── Step 2: Score ─────────────────────────────────
    log.info("STEP 2 — Scoring jobs...")
    try:
        from agents.scorer import run_scorer
        results = run_scorer()
        auto    = len(results["auto"])
        review  = len(results["review"])
        skipped = len(results["skip"])
        log.info(f"Scorer complete — Auto: {auto} | Review: {review} | Skipped: {skipped}")
    except Exception as e:
        log.error(f"Scorer failed: {e}")
        sys.exit(1)

    # ── Step 3: Notify ────────────────────────────────
    log.info("STEP 3 — Sending Discord notifications...")
    try:
        from agents.notifier import run_notifier
        run_notifier()
        log.info("Notifier complete")
    except Exception as e:
        log.error(f"Notifier failed: {e}")

    # ── Summary ───────────────────────────────────────
    elapsed = int((datetime.now() - start).total_seconds())
    log.info(f"{'='*50}")
    log.info(f"Pipeline complete in {elapsed}s")
    log.info(f"  New jobs scraped: {len(new_jobs)}")
    log.info(f"  Auto-apply queue: {auto}")
    log.info(f"  Needs review:     {review}")
    log.info(f"  Skipped:          {skipped}")
    log.info(f"Next step: check Discord, then review jobs in the dashboard (localhost:8501)")
    log.info(f"{'='*50}")


def _send_discord_summary(auto: int, review: int, skipped: int) -> None:
    """Send a brief no-new-jobs summary to Discord."""
    import os
    import asyncio
    import discord
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")

    token      = os.getenv("DISCORD_BOT_TOKEN")
    channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
    if not token or not channel_id:
        return

    async def _notify():
        intents = discord.Intents.default()
        client  = discord.Client(intents=intents)

        @client.event
        async def on_ready():
            ch = client.get_channel(channel_id)
            if ch:
                await ch.send(
                    f"🤖 **Pipeline ran — no new jobs today.**\n"
                    f"Auto-apply: {auto} | Review: {review} | Skipped: {skipped}"
                )
            await client.close()

        await client.start(token)

    asyncio.run(_notify())


if __name__ == "__main__":
    main()
