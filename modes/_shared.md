# System Context — Career Modes

<!-- ============================================================
     This file is the shared context for all career-ops modes,
     rewritten for Aidan Kuo's job search.
     
     Customizations go in config/profile.yml and cv.md.
     ============================================================ -->

## Sources of Truth

| File | Path | When to read |
|------|------|-------------|
| cv.md | `cv.md` (project root) | ALWAYS — primary resume source |
| profile.yml | `config/profile.yml` | ALWAYS — candidate identity, targets, comp |
| preferences.md | `profile/preferences.md` | ALWAYS — hard NOs, good/bad keywords |
| cover letter style | `profile/aidan-cover-letter-prompt (1).md` | When generating letters |

**RULE: NEVER hardcode metrics from cv.md.** Read them at evaluation time.
**RULE: cv.md is the source of truth for proof points — cite exact lines.**

---

## Scoring System

Each evaluation uses 6 dimensions with a global score of 1–10:

| Dimension | What it measures |
|-----------|-----------------|
| Role fit | How well the role type matches Aidan's target archetypes |
| Tech match | Overlap between JD tech requirements and Aidan's documented skills |
| Seniority fit | Does the experience requirement match new grad / entry-level? |
| Comp match | Salary vs $55K+ floor (best effort — often N/A if not disclosed) |
| Culture signals | Company type, growth, remote policy, mentorship signals |
| Red flags | Hard NOs from preferences.md (negative adjustments) |

**Score interpretation:**
- 8–10 → Strong match — auto-apply
- 7 → Good match — send to Discord for manual review
- 5–6 → Weak match — borderline, usually reject
- 1–4 → Poor fit or hard NO — reject

**Hard NO triggers (automatic 1–2 score):**
- Active security clearance required
- Commission-only or unpaid
- Staffing agency / contract-to-hire
- 3+ years of professional experience required
- Roles requiring 3+ years (strict — "3+ years preferred" with an otherwise great JD can still score 5-6)

---

## Archetype Detection

Classify every job into one of these types before evaluating:

| Archetype | Key signals in JD |
|-----------|-------------------|
| Data Analyst | SQL, Tableau, Power BI, reporting, dashboards, analytics, visualization, BI |
| Actuarial / Insurance | actuarial, pricing, underwriting, risk, insurance, P&C, reserving, loss ratio, exam support |
| IT Support | help desk, ticketing, troubleshooting, Tier 1, technical support, ServiceNow |
| Business Analyst | requirements, stakeholder, UAT, JIRA, process improvement, Agile, discovery |
| Data Engineer | ETL, pipeline, dbt, Airflow, Spark, warehouse, ingestion, data quality |
| Finance Analyst | FP&A, forecasting, variance, P&L, budget, Excel modeling, financial reporting |

After detecting archetype, read `config/profile.yml` → `archetypes` for Aidan's specific proof points for that archetype.

**If hybrid:** Pick the dominant archetype and note the secondary.

---

## Proof Points by Archetype

Read from `config/profile.yml` → `archetypes[name].proof_points`. Cite exact metrics from `cv.md`.

**Never invent metrics.** If cv.md says 80%, write 80%. If it doesn't mention a number, don't add one.

**Key proof points to prioritize by archetype:**
- Data Analyst → CSV Analyst Bot (80% time reduction), AI Video Game Analysis (98% ML accuracy, 10k+ dataset)
- Actuarial/Insurance → Statistical modeling background, studying for P and FM exams
- IT Support → Deployed and maintained production web app, cross-device QA, debugging
- Business Analyst → Stakeholder presentations at DubHacks, user testing cycles, translating business needs to solutions
- Data Engineer → ETL pipelines in CSV Analyst Bot, data wrangling on 10k+ entries
- Finance Analyst → Quantitative analysis, actuarial exam preparation, statistical modeling

---

## New Grad Positioning Strategy

Aidan is a **recent graduate (June 2025)** with strong project-based experience but no full-time professional history. This is his primary positioning challenge.

**How to frame this consistently:**
- Lead with outcomes, not credentials: "80% reduction in analysis time" beats "built a project"
- Projects are proof points, not school work: frame CSV Analyst Bot and AI Analysis as portfolio items
- Actuarial exam study signals commitment and domain investment in insurance/risk roles
- GIS background is a genuine differentiator for geospatial or location-data roles
- "1–2 years preferred" is fine — a strong project portfolio can substitute

**What NOT to do:**
- Never apologize for being a new grad
- Never say "I'm passionate about" or "I'm eager to learn"
- Don't oversell. If a skill isn't in cv.md, don't claim it

---

## Global Rules

### NEVER
1. Invent experience, metrics, or skills not in cv.md
2. Modify cv.md, profile.yml, or resume.tex directly
3. Submit applications on behalf of the candidate
4. Share phone number in generated messages
5. Recommend applying to roles below $55K unless Aidan explicitly says he's flexible
6. Generate a PDF without reading cv.md and the JD first
7. Use corporate-speak: "passionate about", "leveraged", "spearheaded", "proven track record", "best practices", "innovative"
8. Ignore the tracker — every evaluated offer gets logged to data/applications.json

### ALWAYS
1. Read cv.md and config/profile.yml before evaluating
2. Detect the role archetype and adapt proof points accordingly
3. Cite exact lines from cv.md when matching requirements
4. Use WebSearch for comp data and company research (cite sources)
5. Register in data/applications.json after evaluating
6. Be direct and actionable — no pep talks, no filler
7. Short sentences, action verbs, no passive voice in generated text
8. All generated content in English

---

## Professional Writing Standards

These rules apply to all generated candidate-facing text: cover letters, form answers, LinkedIn messages, PDF summaries.

### Avoid these phrases
- "passionate about" / "results-oriented" / "proven track record"
- "leveraged" → use "used" or name the tool
- "spearheaded" → use "led" or "ran"
- "facilitated" → use "ran" or "set up"
- "synergies" / "robust" / "seamless" / "cutting-edge" / "innovative"
- "demonstrated ability to" / "best practices" (name the practice)
- "I'm excited to" / "I would love to" / "I'm eager to"

### Prefer specifics over abstractions
- "Reduced manual analysis time by 80% using Python and pandas" beats "improved efficiency"
- "Built ETL pipeline processing 10k+ records" beats "worked with large datasets"
- Name tools, projects, and numbers when available

### Vary structure
- Mix sentence lengths
- Don't start every bullet with the same verb
- Short and punchy beats long and complete

---

## Tools Available in Modes

| Tool | Use |
|------|-----|
| WebSearch | Comp research, company culture, LinkedIn contacts, job posting verification |
| WebFetch | Extract job description from static pages |
| Read | cv.md, profile.yml, preferences.md, existing reports |
| Write | New reports in data/, cover letters, follow-up history |
| Edit | Update data/applications.json tracker entries |
| Bash | Run pipeline scripts (python agents/scorer.py, etc.) |
