# Mode: deep — Company Research Prompt

Generates a structured research prompt for Perplexity, Claude, or manual research across 6 axes.
Run this before an interview or when evaluating a company you're seriously considering.

---

## Deep Research: [Company] — [Role]

**Context:** Evaluating a [role] opportunity at [company]. Need actionable intelligence for the application and interview.

---

### Axis 1 — Data & Analytics Strategy

- Does the company have a dedicated data/analytics team?
- What tools do they use? (SQL, Python, Tableau, dbt, Spark, etc.)
- Do they have an engineering blog? What do they publish?
- Any public talks, papers, or datasets that signal their data maturity?
- Is data analyst work self-serve or centralized?

### Axis 2 — Recent Signals (last 6 months)

- Any relevant hires in data, analytics, or the department of this role?
- Acquisitions, partnerships, or product launches?
- Funding rounds or leadership changes?
- Layoffs or hiring freezes? (check Layoffs.fyi, TechCrunch, LinkedIn)

### Axis 3 — Company Culture & Engineering

- Remote-first or in-office? What's the real day-to-day culture?
- How do they ship? Cadence, autonomy level, tooling?
- Glassdoor and Blind reviews — what do employees say about career growth?
- Is this a data-informed company or data-decorated? (Do leaders use data to make decisions, or just report on it?)

### Axis 4 — Likely Challenges

- What scaling or data quality problems are they probably facing?
- What pain points do employees mention in reviews?
- Is the role new or a backfill? (backfill = existing processes; new = more ambiguity)
- What would the first 90 days likely look like?

### Axis 5 — Competitors & Differentiation

- Who are their main competitors?
- What is their real moat or differentiator?
- How do they position themselves in the market?
- Is the industry growing or contracting?

### Axis 6 — Candidate Angle

Read `cv.md` and `config/profile.yml` before answering:
- Which of Aidan's projects is most relevant to this company's specific work?
- What unique value does a GIS / data science background bring to this company?
- What story should Aidan tell in an interview that no other candidate can tell?
- Is there an actuarial or insurance angle if relevant to this company?

---

## How to use

Paste this prompt into Perplexity (for live web search) or run as a Claude Web Search query.
Customize each axis with the specific company name and role before running.

Save research findings to `data/reports/{company-slug}-deep-research.md` for interview prep.
