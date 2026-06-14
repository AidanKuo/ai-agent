# Mode: pdf — ATS-Optimized Resume PDF Generation

Generates a tailored resume PDF for a specific job. Uses keyword injection based on the JD — never invents skills.

---

## Pipeline

1. Read `cv.md` as the source of truth
2. Get the job description (text or URL)
3. Extract 10–15 keywords from the JD that Aidan genuinely has
4. Detect JD language → generate in English (default)
5. Detect company location → paper format: US/Canada = letter, elsewhere = A4
6. Detect role archetype → adapt proof point emphasis
7. Rewrite Professional Summary injecting JD keywords (stay true to cv.md)
8. Select top 2–3 most relevant projects for this role
9. Reorder project bullets by relevance to JD
10. Build Core Competencies grid from JD requirements (6–8 keyword phrases)
11. Inject keywords naturally into existing bullets (NEVER invent)
12. Generate output via one of two routes:

**Route A — Python pipeline (automated):**
```python
from agents.pdf_generator import render_resume_pdf
path = render_resume_pdf(tailored_md, job=job)
# → data/resumes/YYYYMMDD_{Company}_{Role}.pdf
```

**Route B — Manual (Claude Code):**
Generate the tailored content here, then ask Aidan to paste it into his resume template or provide it as structured text.

---

## ATS Rules (universal)

- Single-column layout — no sidebars, no multi-column tables
- Standard section headers: Professional Summary, Projects, Education, Skills
- No text in images or SVGs
- UTF-8, selectable text (not rasterized)
- Keywords distributed: Summary (top 5), first bullet of each section, Skills

---

## Keyword Injection Strategy (ethical — based on truth only)

**Legitimate reformulation examples:**
- JD says "ETL pipeline" and cv.md says "data pipeline" → use "ETL pipeline for CSV data processing"
- JD says "data visualization" and cv.md says "dynamic charts" → use "data visualization with Matplotlib and Seaborn"
- JD says "stakeholder reporting" and cv.md says "presented findings" → use "stakeholder reporting and data-driven presentations"

**NEVER add skills that aren't in cv.md. Only reformulate existing experience with the JD's vocabulary.**

---

## Section Order (optimized for 6-second recruiter scan)

1. Header (name, contact, LinkedIn, GitHub)
2. Professional Summary (3–4 lines, keyword-dense, tailored to this JD)
3. Core Competencies (6–8 keyword phrases in a grid)
4. Projects (top 2–3 most relevant)
5. Education
6. Skills

---

## Core Competencies Grid

Select 6–8 from JD requirements that Aidan genuinely has. Format as a compact grid:

```
SQL · Python · Tableau · Power BI · pandas · ETL Pipelines · Data Visualization · Stakeholder Reporting
```

---

## Professional Summary Template

Rewrite cv.md summary to front-load JD keywords:

```
[JD keyword 1] and [JD keyword 2] specialist with [strongest proof point from cv.md].
[Second proof point with metric]. Seeking [role title] role at [company type].
```

**Example:** "Data Analyst and ETL pipeline builder with 80% reduction in manual analysis time using Python and pandas. Built ML model achieving 98% accuracy on 10,000+ entry dataset. Seeking entry-level analytics engineer role."

---

## Post-generation

Update `data/applications.json` → set `tailored_resume_path` for the job.
