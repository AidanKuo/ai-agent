import asyncio
import json
import logging
import os
from pathlib import Path

import discord
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

BASE_DIR  = Path(__file__).parent.parent
CONFIG    = BASE_DIR / "config" / "settings.yaml"
APPS_PATH = BASE_DIR / "data" / "applications.json"

TOKEN      = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))


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


def find_job_by_id(apps: list[dict], job_id: str) -> dict | None:
    return next((j for j in apps if j["id"] == job_id), None)


def format_job_embed(job: dict) -> discord.Embed:
    """Build a rich Discord embed for a single job."""
    score = job.get("score", 0)

    # Color based on score
    if score >= 8:
        color = discord.Color.green()
    elif score >= 6:
        color = discord.Color.gold()
    else:
        color = discord.Color.light_grey()

    embed = discord.Embed(
        title=f"{job['title']}",
        url=job.get("job_url", ""),
        description=f"**{job['company']}** — {job['location']}",
        color=color,
    )

    embed.add_field(name="Score", value=f"{score}/10", inline=True)
    embed.add_field(name="Site",  value=job.get("site", "—").capitalize(), inline=True)
    embed.add_field(name="Remote", value="Yes" if job.get("is_remote") else "No", inline=True)

    if job.get("reasoning"):
        embed.add_field(name="Why this score", value=job["reasoning"], inline=False)

    if job.get("salary_min") and job.get("salary_max"):
        embed.add_field(
            name="Salary",
            value=f"${job['salary_min']} – ${job['salary_max']}",
            inline=False
        )

    embed.set_footer(text=f"ID: {job['id'][:8]}... | Reply with the ID + approve/reject/skip")
    return embed


# ── Discord bot ───────────────────────────────────────────────────────────────

class ApprovalBot(discord.Client):
    def __init__(self, jobs_to_review: list[dict], **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, **kwargs)
        self.jobs_to_review = jobs_to_review
        self.pending: dict[str, dict] = {}   # short_id → job

    async def on_ready(self):
        log.info(f"Discord bot ready as {self.user}")
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            log.error(f"Channel {CHANNEL_ID} not found — check DISCORD_CHANNEL_ID in .env")
            await self.close()
            return

        if not self.jobs_to_review:
            await channel.send("✅ **No jobs need review right now.** Auto-apply queue is ready.")
            await self.close()
            return

        await channel.send(
            f"📋 **{len(self.jobs_to_review)} job(s) need your review.**\n"
            f"Reply: `<ID> ✅` or `y` = approve · `❌` or `n` = reject · `⏭️` or `s` = skip\n"
            f"Example: `a1b2c3d4 ✅` or `a1b2c3d4 y`\n"
            f"{'─'*40}"
        )

        for job in self.jobs_to_review:
            short_id = job["id"][:8]
            self.pending[short_id] = job
            embed = format_job_embed(job)
            await channel.send(f"**ID: `{short_id}`**", embed=embed)
            await asyncio.sleep(0.5)   # avoid rate limiting

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return
        if message.channel.id != CHANNEL_ID:
            return

        parts = message.content.strip().lower().split()
        if len(parts) < 2:
            return

        short_id, action = parts[0], parts[1]

        if short_id not in self.pending:
            return

        EMOJI_MAP = {
            "approve": "auto_apply", "✅": "auto_apply", "👍": "auto_apply", "y": "auto_apply",
            "reject":  "rejected",   "❌": "rejected",   "👎": "rejected",   "n": "rejected",
            "skip":    "skipped",    "⏭": "skipped",    "⏭️": "skipped",    "s": "skipped",
        }

        if action not in EMOJI_MAP:
            await message.channel.send(
                f"❓ Unknown action. Use: ✅ 👍 y = approve | ❌ 👎 n = reject | ⏭️ s = skip"
            )
            return

        job = self.pending.pop(short_id)
        apps = load_applications()
        full_job = find_job_by_id(apps, job["id"])
        status = EMOJI_MAP[action]
        full_job["status"] = status

        icons = {"auto_apply": "✅", "rejected": "❌", "skipped": "⏭️"}
        labels = {"auto_apply": "Approved", "rejected": "Rejected", "skipped": "Skipped"}
        await message.channel.send(f"{icons[status]} **{labels[status]}:** {job['title']} @ {job['company']}")
        log.info(f"{labels[status]}: {job['title']} @ {job['company']}")
        save_applications(apps)

        # All reviewed — close bot
        if not self.pending:
            await message.channel.send(
                f"✅ **All jobs reviewed.** "
                f"Run `python agents/applicator.py` to process the approved queue."
            )
            await asyncio.sleep(1)
            await self.close()


# ── Auto-apply notifier ───────────────────────────────────────────────────────

async def notify_auto_apply(jobs: list[dict]) -> None:
    """Send a summary of auto-apply jobs to Discord (no approval needed)."""
    intents = discord.Intents.default()
    client  = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            await client.close()
            return

        if not jobs:
            await client.close()
            return

        lines = "\n".join(
            f"  `[{j['score']}/10]` {j['title']} @ {j['company']}"
            for j in jobs[:20]   # cap at 20 to avoid spam
        )
        await channel.send(
            f"🤖 **Auto-applying to {len(jobs)} job(s):**\n{lines}\n"
            f"{'─'*40}\n"
            f"_Run `python agents/applicator.py` to execute._"
        )
        await client.close()

    await client.start(TOKEN)


# ── Entry point ───────────────────────────────────────────────────────────────

def run_notifier() -> None:
    if not TOKEN:
        log.error("DISCORD_BOT_TOKEN not set in .env")
        return
    if not CHANNEL_ID:
        log.error("DISCORD_CHANNEL_ID not set in .env")
        return

    apps           = load_applications()
    needs_review   = [j for j in apps if j.get("status") == "needs_review"]
    auto_apply     = [j for j in apps if j.get("status") == "auto_apply"]

    log.info(f"Needs review: {len(needs_review)} | Auto-apply: {len(auto_apply)}")

    # Send auto-apply summary first
    if auto_apply:
        asyncio.run(notify_auto_apply(auto_apply))

    # Then run interactive review bot
    if needs_review:
        bot = ApprovalBot(jobs_to_review=needs_review)
        bot.run(TOKEN)
    else:
        log.info("No jobs need review — nothing to do.")


if __name__ == "__main__":
    run_notifier()
