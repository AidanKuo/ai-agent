import asyncio
import json
import logging
import os
from pathlib import Path

import discord
import yaml
from dotenv import load_dotenv

# ── Setup ─────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent.parent / ".env")
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

APPROVE_EMOJI = "✅"
REJECT_EMOJI  = "❌"
SKIP_EMOJI    = "⏭️"

REACTION_MAP = {
    "✅": "auto_apply",
    "❌": "rejected",
    "⏭️": "skipped",
    "⏭":  "skipped",
}


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
    score = job.get("score", 0)

    if score >= 8:
        color = discord.Color.green()
    elif score >= 6:
        color = discord.Color.gold()
    else:
        color = discord.Color.light_grey()

    embed = discord.Embed(
        title=job["title"],
        url=job.get("job_url", ""),
        description=f"**{job['company']}** — {job['location']}",
        color=color,
    )

    embed.add_field(name="Score",  value=f"{score}/10",                           inline=True)
    embed.add_field(name="Site",   value=job.get("site", "—").capitalize(),        inline=True)
    embed.add_field(name="Remote", value="Yes" if job.get("is_remote") else "No",  inline=True)

    if job.get("ats_score") is not None:
        embed.add_field(name="ATS Score", value=f"{job['ats_score']}/100", inline=True)

    if job.get("reasoning"):
        embed.add_field(name="Why this score", value=job["reasoning"], inline=False)

    if job.get("ats_score_reasoning"):
        embed.add_field(name="ATS reasoning", value=job["ats_score_reasoning"], inline=False)

    if job.get("salary_min") and job.get("salary_max"):
        embed.add_field(
            name="Salary",
            value=f"${job['salary_min']} – ${job['salary_max']}",
            inline=False,
        )

    embed.set_footer(text="React ✅ approve · ❌ reject · ⏭️ skip")
    return embed


# ── Bot ───────────────────────────────────────────────────────────────────────

class ApprovalBot(discord.Client):
    def __init__(self, jobs_to_review: list[dict], **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        super().__init__(intents=intents, **kwargs)
        self.jobs_to_review = jobs_to_review
        self.pending_by_msg: dict[int, dict] = {}

    async def on_ready(self):
        log.info(f"Discord bot ready as {self.user}")
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            log.error(f"Channel {CHANNEL_ID} not found")
            await self.close()
            return

        if not self.jobs_to_review:
            await channel.send("✅ **No jobs need review right now.**")
            await self.close()
            return

        await channel.send(
            f"📋 **{len(self.jobs_to_review)} job(s) need your review.**\n"
            f"React on each card:  ✅ approve  ·  ❌ reject  ·  ⏭️ skip\n"
            f"{'─'*40}"
        )

        for job in self.jobs_to_review:
            embed = format_job_embed(job)
            msg = await channel.send(embed=embed)
            await msg.add_reaction(APPROVE_EMOJI)
            await msg.add_reaction(REJECT_EMOJI)
            await msg.add_reaction(SKIP_EMOJI)
            self.pending_by_msg[msg.id] = job
            log.info(f"  Posted: {job['title']} @ {job['company']} (msg {msg.id})")
            await asyncio.sleep(0.75)

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user == self.user:
            return
        if reaction.message.id not in self.pending_by_msg:
            return

        emoji = str(reaction.emoji)
        if emoji not in REACTION_MAP:
            return

        job      = self.pending_by_msg.pop(reaction.message.id)
        apps     = load_applications()
        full_job = find_job_by_id(apps, job["id"])
        if full_job is None:
            log.warning(f"Reaction received for unknown job ID: {job['id']}")
            return
        status   = REACTION_MAP[emoji]
        full_job["status"] = status
        save_applications(apps)

        icons  = {"auto_apply": "✅", "rejected": "❌", "skipped": "⏭️"}
        labels = {"auto_apply": "Approved", "rejected": "Rejected", "skipped": "Skipped"}
        log.info(f"{labels[status]}: {job['title']} @ {job['company']}")

        channel = self.get_channel(CHANNEL_ID)
        await channel.send(
            f"{icons[status]} **{labels[status]}:** {job['title']} @ {job['company']}"
        )

        if not self.pending_by_msg:
            await channel.send(
                "✅ **All jobs reviewed.**\n"
                "Run `python agents/applicator.py` to process the approved queue."
            )
            await asyncio.sleep(1)
            await self.close()


# ── Auto-apply notifier ───────────────────────────────────────────────────────

async def notify_auto_apply(jobs: list[dict]) -> None:
    intents = discord.Intents.default()
    client  = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            await client.close()
            return

        lines = "\n".join(
            f"  `[{j['score']}/10]` {j['title']} @ {j['company']}"
            for j in jobs[:20]
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

    apps         = load_applications()
    needs_review = [j for j in apps if j.get("status") == "needs_review"]
    auto_apply   = [j for j in apps if j.get("status") == "auto_apply"]

    log.info(f"Needs review: {len(needs_review)} | Auto-apply: {len(auto_apply)}")

    if auto_apply:
        asyncio.run(notify_auto_apply(auto_apply))

    if needs_review:
        bot = ApprovalBot(jobs_to_review=needs_review)
        bot.run(TOKEN)
    else:
        log.info("No jobs need review — nothing to do.")


if __name__ == "__main__":
    run_notifier()
