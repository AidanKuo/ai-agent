"""
agents/bot.py

Persistent Discord bot — stays online 24/7.
@ mention it to chat, ask about your applications, or get pipeline status.

Run it in a dedicated terminal:
    .venv\\Scripts\\Activate.ps1
    python agents/bot.py

Keep this running separately from the pipeline.
"""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import discord
import ollama
import yaml
from dotenv import load_dotenv

# ── Setup ─────────────────────────────────────────────────────────────────────

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).parent.parent
CONFIG    = BASE_DIR / "config" / "settings.yaml"
APPS_PATH = BASE_DIR / "data" / "applications.json"
PREFS     = BASE_DIR / "profile" / "preferences.md"

TOKEN      = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

MAX_HISTORY = 10   # messages to keep in conversation memory per session


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG) as f:
        return yaml.safe_load(f)


def load_applications() -> list[dict]:
    if not APPS_PATH.exists():
        return []
    with open(APPS_PATH) as f:
        return json.load(f)


def get_application_summary() -> str:
    """Build a concise summary of application data for the LLM context."""
    apps = load_applications()
    if not apps:
        return "No applications logged yet."

    total     = len(apps)
    applied   = [a for a in apps if a.get("status") == "applied"]
    auto_q    = [a for a in apps if a.get("status") == "auto_apply"]
    review_q  = [a for a in apps if a.get("status") == "needs_review"]
    skipped   = [a for a in apps if a.get("status") == "skipped"]
    rejected  = [a for a in apps if a.get("status") == "rejected"]
    scored    = [a for a in apps if a.get("score") is not None]
    avg_score = round(sum(a["score"] for a in scored) / len(scored), 1) if scored else 0

    top = sorted(scored, key=lambda x: x["score"], reverse=True)[:5]
    top_list = "\n".join(
        f"  - [{a['score']}/10] {a['title']} @ {a['company']}"
        for a in top
    )

    recent_applied = sorted(applied, key=lambda x: x.get("applied_at", ""), reverse=True)[:5]
    recent_list = "\n".join(
        f"  - {a['title']} @ {a['company']} ({a.get('applied_at','?')[:10]})"
        for a in recent_applied
    ) or "  None yet"

    return f"""APPLICATION DATA SUMMARY (as of {datetime.now().strftime('%Y-%m-%d %H:%M')}):
Total jobs in database: {total}
Applied: {len(applied)}
In auto-apply queue: {len(auto_q)}
Awaiting your review: {len(review_q)}
Skipped (low fit): {len(skipped)}
Rejected by you: {len(rejected)}
Average fit score: {avg_score}/10

Top scored jobs:
{top_list}

Most recently applied:
{recent_list}"""


def build_system_prompt() -> str:
    cfg = load_config()
    app_summary = get_application_summary()
    return f"""You are an AI job search assistant for Aidan Kuo, a junior data analyst in Houston TX.
You help Aidan manage his automated job application pipeline built with OpenClaw.

CURRENT PIPELINE SETTINGS:
- Model: {cfg['model']['name']}
- Auto-apply threshold: {cfg['scoring']['auto_apply_threshold']}/10
- Review threshold: {cfg['scoring']['review_threshold']}/10
- Max applications/day: {cfg['scoring']['max_applications_per_day']}
- Search terms: {', '.join(cfg['scraper']['search_terms'])}
- Locations: {', '.join(cfg['scraper']['locations'])}

{app_summary}

You can help with:
- Questions about job applications, scores, pipeline status
- Advice on job searching, resume improvements, interview prep
- General coding or data analysis questions
- Explaining how the pipeline works

Keep responses concise — this is Discord, not a document. Use bullet points for lists.
If asked to run the pipeline, explain that Aidan needs to run it manually from the terminal.
Never make up application data — only reference what's in the summary above."""


# ── Bot ───────────────────────────────────────────────────────────────────────

class JobBot(discord.Client):
    def __init__(self, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, **kwargs)
        # Per-channel conversation history
        self.history: list[dict] = []

    async def on_ready(self):
        log.info(f"Bot online as {self.user} (ID: {self.user.id})")
        channel = self.get_channel(CHANNEL_ID)
        if channel:
            await channel.send("🤖 Job assistant online. @ me to chat.")

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return
        if message.channel.id != CHANNEL_ID:
            return

        # Only respond to @ mentions
        if self.user not in message.mentions:
            return

        # Strip the mention from the message
        content = re.sub(r"<@!?\d+>", "", message.content).strip()
        if not content:
            await message.channel.send("Hey! Ask me anything about your job search.")
            return

        log.info(f"Message from {message.author}: {content[:80]}")

        # Show typing indicator while generating
        async with message.channel.typing():
            try:
                cfg    = load_config()
                model  = cfg["model"]["name"]
                system = build_system_prompt()

                # Add user message to history
                self.history.append({"role": "user", "content": content})

                # Keep history bounded
                if len(self.history) > MAX_HISTORY * 2:
                    self.history = self.history[-(MAX_HISTORY * 2):]

                # Call Ollama with conversation history
                messages = [{"role": "system", "content": system}] + self.history

                response = ollama.chat(
                    model=model,
                    messages=messages,
                    options={"temperature": 0.5},
                )
                reply = response["message"]["content"].strip()

                # Add assistant reply to history
                self.history.append({"role": "assistant", "content": reply})

                # Discord has a 2000 char limit — split if needed
                if len(reply) <= 1900:
                    await message.reply(reply)
                else:
                    chunks = [reply[i:i+1900] for i in range(0, len(reply), 1900)]
                    for i, chunk in enumerate(chunks):
                        if i == 0:
                            await message.reply(chunk)
                        else:
                            await message.channel.send(chunk)

            except Exception as e:
                log.error(f"Response failed: {e}")
                await message.reply("Something went wrong — check the bot logs.")

    async def on_disconnect(self):
        log.warning("Bot disconnected — will attempt reconnect")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not TOKEN:
        log.error("DISCORD_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not CHANNEL_ID:
        log.error("DISCORD_CHANNEL_ID not set in .env")
        sys.exit(1)

    log.info("Starting persistent job assistant bot...")
    bot = JobBot()
    bot.run(TOKEN, log_handler=None)
