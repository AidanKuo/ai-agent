# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project is an automated job application pipeline. It scrapes job postings, scores them with a local LLM (Ollama), sends a daily Discord briefing, and provides a Dash dashboard for reviewing jobs and tracking applications. All application state lives in `data/applications.json`.

## Running the Project

**Prerequisites**: Ollama running locally at `http://localhost:11434` with `gemma3:12b` model, Discord bot token in `.env`, Anthropic API key in `.env`, Python venv at `.venv/`.

```bash
# Dashboard only
python dash_app.py  # runs on http://localhost:8050

# Full pipeline (scrape → score → Discord briefing)
python run_pipeline.py

# Individual agents
python agents/scraper.py
python agents/scorer.py
```

The pipeline runs daily at 9 AM via a Windows Task Scheduler task.

## Architecture

### Data Flow

```
run_pipeline.py → scraper.py → scorer.py → Discord briefing (inline)
                      ↓             ↓
                applications.json (shared state for all agents)
                      ↑
                dash_app.py (Dash UI for review/apply tracking)
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

- **scraper.py**: Uses `jobspy` to query Indeed, LinkedIn, ZipRecruiter. Deduplicates via UUID5 stable IDs (`uuid5(title|company|location)`). Hard-filters before scoring: senior title regex (Senior/Sr/Lead/Principal/Staff/Manager/II–IV etc., title only), ≥3-years-required regex (full JD text, "1-3 years" junior ranges allowed), then literal bad keywords from `preferences.md`.
- **scorer.py**: Sends job description + resume + preferences to Ollama (`gemma3:12b`, temp 0.1). Structured output: SCORE, ARCHETYPE, TECH_MATCH, SENIORITY_FIT, GAPS. Score ≥ 7 → `auto_apply`, else → `rejected`. Prompt lives in `config/scoring_prompt.md`.
- **portal_scanner.py**: Hits Greenhouse, Ashby, and Lever APIs directly (zero-LLM). Filters by title keywords from `config/portals.yml`. Writes to applications.json in same format as scraper.
- **pdf_generator.py**: Renders a tailored resume markdown to PDF via Playwright/Chromium. Parses cv.md structure, fills `templates/cv-template.html`, outputs to `data/resumes/`. CLI: `python agents/pdf_generator.py [--job JOB_ID | --md FILE]`. Programmatic: `from agents.pdf_generator import render_resume_pdf`.
- **dash_app.py**: Dash UI on port 8050. Single Dashboard page: pipeline progress banner, filters (status, search group, apply-path source), job list, and a detail panel (score reasoning, apply actions: Mark Applied / Skip / status dropdown). Filters by status, search group, and apply-path source (Apply Direct / Indeed / LinkedIn direct / LinkedIn no-direct-URL); the detail header links to the direct ATS apply URL when one exists, falling back to the aggregator posting.

### Library Modules (`lib/`)

| File | Role |
|------|------|
| `lib/constants.py` | Path constants (BASE_DIR, APPS_PATH, LOG_PATH, CONFIG_PATH) |
| `lib/pipeline_log.py` | Appends every new job to `data/pipeline.md` (human-readable markdown table log, written by scraper and portal scanner) |

### Other Files

| File | Role |
|------|------|
| `run_pipeline.py` | Orchestrates scraper → scorer → Discord briefing (all inline, no separate notifier module) |
| `assets/jarvis.css` | Dash static stylesheet |
| `templates/cv-template.html` | HTML resume template (filled + rendered to PDF by pdf_generator.py) |
| `cv.md` | Resume in markdown — source of truth for pdf_generator and career-ops modes |
| `config/profile.yml` | Candidate identity: name, email, phone, LinkedIn, GitHub, education, auth status |
| `config/scoring_prompt.md` | LLM scoring prompt template (editable without touching scorer.py) |
| `modes/` | Career-ops mode files: apply, followup, contacto, interview-prep, pdf, oferta, deep |

## Career-Ops Integration

The `modes/` folder contains career-ops mode files that turn Claude Code into an interactive job application assistant. Modes are plain-English instruction files — Claude reads them and executes the workflow described inside.

### Modes Reference

| Mode | File | What it does |
|------|------|-------------|
| `oferta` | `modes/oferta.md` | Full 7-block job evaluation: role summary, CV match, seniority positioning, comp research, personalization plan, interview prep, posting legitimacy check |
| `deep` | `modes/deep.md` | Deep company research across 6 axes: data strategy, recent signals, culture, likely challenges, competitors, candidate angle |
| `interview-prep` | `modes/interview-prep.md` | Interview intelligence report: researches actual questions via Glassdoor/Blind, generates STAR stories mapped to cv.md proof points, builds a technical prep checklist |
| `pdf` | `modes/pdf.md` | ATS-optimized tailored resume: extracts JD keywords, injects into cv.md, calls `agents/pdf_generator.py`, outputs to `data/resumes/` |
| `apply` | `modes/apply.md` | Live application form assistant: reads form questions, generates copy-paste answers, updates applications.json on submit |
| `followup` | `modes/followup.md` | Follow-up cadence tracker: checks days since applied, generates follow-up drafts, records sent follow-ups |
| `contacto` | `modes/contacto.md` | LinkedIn outreach: finds the right contact at a company (hiring manager > recruiter > peer), generates a 300-char message |

### The "Evaluate Job" Workflow

**Trigger:** Say `evaluate job #42`, `evaluate [Company]`, or `evaluate job <id>`.

When triggered, Claude will:

1. **Find the job** in `data/applications.json`:
   - By array index: `#42` → `apps[42]`
   - By company name (case-insensitive substring match)
   - By job ID prefix (first 8 chars of the UUID)
   ```python
   # Quick lookup from CLI:
   python -c "
   import json; apps = json.load(open('data/applications.json'))
   j = apps[42]  # or next(x for x in apps if 'Company' in x.get('company',''))
   print(j['id'], j['title'], '@', j['company'])
   "
   ```

2. **Load context** — read `cv.md`, `config/profile.yml`, `profile/preferences.md`

3. **Run `oferta` evaluation** (all 7 blocks):
   - Block A: Role summary + archetype
   - Block B: CV match table (JD requirements → cv.md lines, strength rating)
   - Block C: New grad positioning strategy
   - Block D: Comp research (WebSearch for salary ranges vs $55K floor)
   - Block E: Top 5 keyword injection changes to cv.md for this JD
   - Block F: 5–7 likely interview questions mapped to proof points
   - Block G: Posting legitimacy assessment

4. **Save report** to `data/reports/{###}-{company-slug}-{YYYY-MM-DD}.md`
   - `{###}` = next sequential number (check existing files, zero-pad to 3 digits)

5. **Generate tailored PDF** — apply Block E keyword changes to a copy of cv.md, then:
   ```python
   from agents.pdf_generator import render_resume_pdf
   path = render_resume_pdf(tailored_md, job=job)
   # → data/resumes/YYYYMMDD_{Company}_{Role}.pdf
   ```

6. **Update `data/applications.json`** — add to the job record:
   ```json
   {
     "career_ops_report": "data/reports/042-company-name-2026-05-02.md",
     "tailored_resume":   "data/resumes/20260502_Company_Role.pdf",
     "status":            "auto_apply"
   }
   ```

7. **Deliver a summary** — score, top strength, top gap, next action (apply / review / skip).

### Tailored PDF Only

To regenerate a tailored resume PDF without a full evaluation:

```
generate tailored resume for job #42
```

Claude will read the existing report in `data/reports/` if it exists (skipping re-evaluation), apply the keyword changes from Block E, and call `render_resume_pdf`.

To render the base resume (no tailoring):
```bash
python agents/pdf_generator.py
# → data/resumes/Kuo_Aidan_Resume.pdf
```

### Company Research (Deep Mode)

```
deep research [Company]
```

Runs `modes/deep.md` — a 6-axis research framework covering data strategy, recent hiring signals, culture, likely first-90-days challenges, competitors, and Aidan's specific candidate angle. Saves findings to `data/reports/{company-slug}-deep-research.md`.

Run this before a scheduled interview or when seriously evaluating a company. The `oferta` workflow covers surface-level comp research (Block D); `deep` goes further with engineering blog analysis, Glassdoor/Blind synthesis, and a tailored "what story should Aidan tell" angle.

### Interview Prep + STAR Stories

```
interview prep [Company] [Role]
```

Runs `modes/interview-prep.md`:
1. Researches actual questions via Glassdoor, Blind, LeetCode discuss
2. Builds round-by-round breakdown (duration, format, what they evaluate)
3. Maps likely questions to cv.md proof points with STAR talking points:
   - **DubHacks** → leadership, shipping under pressure, stakeholder communication
   - **CSV Analyst Bot** → solving a real problem independently (80% time reduction)
   - **AI Video Game Analysis** → handling large datasets, statistical rigor (98% ML accuracy)
   - **VetConnect** → user empathy, design thinking, iteration
4. Generates a technical prep checklist based on what the company actually tests
5. Saves full report to `data/reports/{company-slug}-{role-slug}-interview-prep.md`

After delivering the report, offer to simulate the interview (practice answering questions out loud).

### Follow-up Cadence

```
followup
```

Runs `modes/followup.md` — checks all `status: "applied"` jobs, calculates days since `applied_at`, surfaces overdue follow-ups, and drafts tailored messages. Cadence: first follow-up at 7 days, second at 14, mark cold after 2 attempts with no response.

### Quick Reference

| Say this | What happens |
|----------|-------------|
| `evaluate job #42` | Full oferta + report + tailored PDF + status update |
| `evaluate [Company]` | Same, looked up by company name |
| `deep research [Company]` | 6-axis company intelligence report |
| `interview prep [Company] [Role]` | Interview questions + STAR stories + prep checklist |
| `generate tailored resume for job #42` | PDF only, reuses existing report if available |
| `followup` | Follow-up dashboard + drafts for overdue applications |
| `contacto [Company]` | LinkedIn outreach message to hiring manager/recruiter |

### Key Paths

| Item | Path |
|------|------|
| Evaluation reports | `data/reports/{###}-{company-slug}-{YYYY-MM-DD}.md` |
| Interview prep reports | `data/reports/{company-slug}-{role-slug}-interview-prep.md` |
| Deep research | `data/reports/{company-slug}-deep-research.md` |
| Tailored resumes | `data/resumes/YYYYMMDD_{Company}_{Role}.pdf` |
| Base resume PDF | `data/resumes/Kuo_Aidan_Resume.pdf` |
| Cover letters | `data/cover_letters/Kuo_Aidan_CoverLetter.pdf` |

---

## Configuration

All tunable parameters are in `config/settings.yaml` — search terms, max results per term, recency filter (`hours_old`), scoring thresholds, and model name. No code changes needed for common adjustments.

Job preferences and hard filters are in `profile/preferences.md` (plain English, parsed by the LLM prompt).

Cover letter voice and style rules are in `profile/aidan-cover-letter-prompt (1).md`.
