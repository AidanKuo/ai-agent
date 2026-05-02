# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenClaw is an automated job application pipeline. It scrapes job postings, scores them with a local LLM (Ollama), sends a daily Discord briefing, and provides a Dash dashboard for reviewing jobs and tracking applications. All application state lives in `data/applications.json`.

## Running the Project

**Prerequisites**: Ollama running locally at `http://localhost:11434` with `gemma3:12b` model, Discord bot token in `.env`, Anthropic API key in `.env`, Python venv at `.venv/`.

```bash
# Start everything (checks Ollama, verifies model, starts gateway, launches dashboard)
.\start_openclaw.ps1

# Dashboard only
python dash_app.py  # runs on http://localhost:8050

# Full pipeline (scrape → score → Discord briefing)
python run_pipeline.py

# Individual agents
python agents/scraper.py
python agents/scorer.py
```

The pipeline runs daily at 9 AM via Windows Task Scheduler ("OpenClaw Daily Pipeline" task).

## Architecture

### Data Flow

```
run_pipeline.py → scraper.py → scorer.py → Discord briefing (inline)
                      ↓             ↓
                applications.json (shared state for all agents)
                      ↑
                dash_app.py (Dash UI for review/apply/cover letter)
```

### Job Status Lifecycle

Jobs in `data/applications.json` progress through these statuses:
- `scraped` → assigned by scraper
- `auto_apply` (score ≥ 7) or `rejected` (score < 7) → assigned by scorer
- `applied` → set by dashboard after user clicks "Mark Applied"
- `skipped` → set by dashboard after user clicks "Skip"

### Key Files

| File | Role |
|------|------|
| `config/settings.yaml` | Search terms, LLM model, scoring thresholds, site list |
| `profile/preferences.md` | Hard filters and good/bad keywords (parsed at runtime by scorer) |
| `profile/resume.tex` | LaTeX resume (text extracted for LLM context) |
| `profile/aidan-cover-letter-prompt (1).md` | Cover letter style guide (voice + tone rules) |
| `data/applications.json` | Master job database (read/written by all agents) |
| `data/seen_jobs.json` | Job ID dedup set (prevents re-scraping) |
| `.env` | `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, `OLLAMA_HOST`, `ANTHROPIC_API_KEY` |

### Agent Details

- **scraper.py**: Uses `jobspy` to query Indeed, LinkedIn, ZipRecruiter. Deduplicates via UUID5 stable IDs (`uuid5(title|company|location)`). Applies hard keyword filters from `preferences.md`.
- **scorer.py**: Sends job description + resume + preferences to Ollama (`gemma3:12b`, temp 0.1). Structured output: SCORE, ARCHETYPE, TECH_MATCH, SENIORITY_FIT, GAPS. Score ≥ 7 → `auto_apply`, else → `rejected`. Prompt lives in `config/scoring_prompt.md`.
- **ats_scanner.py**: Compares resume keywords against a job description via Ollama. Returns score (0–100), missing keywords, weak bullet rewrites, and improvement suggestions.
- **portal_scanner.py**: Hits Greenhouse, Ashby, and Lever APIs directly (zero-LLM). Filters by title keywords from `config/portals.yml`. Writes to applications.json in same format as scraper.
- **pdf_generator.py**: Renders a tailored resume markdown to PDF via Playwright/Chromium. Parses cv.md structure, fills `templates/cv-template.html`, outputs to `data/resumes/`. CLI: `python agents/pdf_generator.py [--job JOB_ID | --md FILE]`. Programmatic: `from agents.pdf_generator import render_resume_pdf`.
- **dash_app.py**: Dash UI on port 8050. Three tabs: Dashboard (health/topology), Pipeline (job list + detail panel with ATS, Research, Cover Letter, apply actions), Masterlist (Buy/Todo/Watch lists).

### Library Modules (`lib/`)

| File | Role |
|------|------|
| `lib/constants.py` | Path constants (BASE_DIR, APPS_PATH, LETTERS_DIR, etc.) |
| `lib/resume.py` | Cover letter generation: draft via Claude Sonnet, humanize via Claude Haiku, save as PDF (FPDF) |
| `lib/company_researcher.py` | Scrapes company website (requests + bs4), calls Claude Sonnet with 6 research questions to produce personalization context |

### Utility Modules (`utils/`)

| File | Role |
|------|------|
| `utils/gateway.py` | Reads `~/.openclaw/openclaw.json`; provides gateway health check and config access |
| `utils/list_data.py` | CRUD for Buy/Todo/Watch masterlists stored in `data/lists.json` |

### Other Files

| File | Role |
|------|------|
| `manage_list.py` | CLI for ClawBot to manage Buy/Todo/Watch lists (add/remove/done/show) |
| `run_pipeline.py` | Orchestrates scraper → scorer → Discord briefing (all inline, no separate notifier module) |
| `start_openclaw.ps1` | Startup script: checks Ollama, verifies model, starts gateway, launches dashboard |
| `assets/jarvis.css` | Dash static stylesheet |
| `templates/cv-template.html` | HTML resume template (filled + rendered to PDF by pdf_generator.py) |
| `cv.md` | Resume in markdown — source of truth for pdf_generator and career-ops modes |
| `config/profile.yml` | Candidate identity: name, email, phone, LinkedIn, GitHub, education, auth status |
| `config/scoring_prompt.md` | LLM scoring prompt template (editable without touching scorer.py) |
| `modes/` | Career-ops mode files: apply, followup, contacto, interview-prep, pdf, oferta, deep |

### Cover Letter Flow (two-step in dashboard)

1. **Research** button → `lib/company_researcher.py` scrapes company site, calls Claude Sonnet to answer 6 personalization questions. User can edit answers.
2. **Generate Letter** button → `lib/resume.py` takes research context, drafts letter via Claude Sonnet (150-200 words), humanizes via Claude Haiku. Saves to `data/cover_letters/`.

## Configuration

All tunable parameters are in `config/settings.yaml` — search terms, max results per term, recency filter (`hours_old`), scoring thresholds, and model name. No code changes needed for common adjustments.

Job preferences and hard filters are in `profile/preferences.md` (plain English, parsed by the LLM prompt).

Cover letter voice and style rules are in `profile/aidan-cover-letter-prompt (1).md`.
