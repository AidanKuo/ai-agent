# Mode: oferta — Full Job Evaluation (Blocks A–G)

When the candidate pastes a job posting (text or URL), always deliver all 7 blocks.

---

## Step 0 — Archetype Detection

Classify the role into one archetype (see `_shared.md`). If hybrid, note both.

This determines:
- Which proof points to prioritize in Block B
- How to frame Block C seniority positioning
- Which STAR stories to prep in Block F

---

## Block A — Role Summary

| Field | Value |
|-------|-------|
| Archetype | |
| Function | build / analyze / support / consult |
| Seniority | entry-level / junior / mid |
| Remote | remote / hybrid / on-site |
| Team size | (if mentioned) |
| TL;DR | one sentence |

---

## Block B — CV Match

Read `cv.md`. Map each JD requirement to exact lines from the CV.

**Adapt by archetype:**
- Data Analyst → prioritize CSV Analyst Bot (80% time reduction), AI Video Game Analysis (98% ML accuracy), SQL/Python/Tableau/Power BI
- Actuarial/Insurance → prioritize statistical modeling background, actuarial exam study (P, FM)
- IT Support → prioritize DubHacks deployment, debugging, cross-device QA
- Business Analyst → prioritize stakeholder presentations, user testing, translating needs to solutions
- Data Engineer → prioritize ETL pipeline (CSV Analyst Bot), data wrangling on 10k+ entries
- Finance Analyst → prioritize quantitative analysis, statistical modeling, actuarial exam prep

**Requirement mapping table:**

| JD Requirement | CV Match | Strength |
|---------------|----------|----------|
| | | Strong / Partial / Gap |

**Gaps section** — for each gap:
1. Is it a hard blocker or a nice-to-have?
2. Can Aidan demonstrate adjacent experience?
3. Which project is closest to covering this gap?
4. One concrete mitigation phrase for cover letter or form answer

---

## Block C — Seniority Strategy (New Grad Positioning)

1. **Seniority detected in JD** vs **Aidan's actual level** (new grad, June 2025)

2. **"Projects as experience" framing** — how to position project work as equivalent to professional experience for this specific role:
   - Which 1–2 projects are most relevant?
   - What outcome metrics to lead with?
   - How to acknowledge being a new grad without apologizing for it

3. **If the role says "1–2 years preferred":** Confirm this is worth applying to (it is). Draft a one-line framing that bridges the gap.

4. **If the role requires 3+ years:** Flag as likely mismatch. Only proceed if Aidan explicitly confirms.

---

## Block D — Comp & Market Research

Use WebSearch:
- Current salary ranges for this role and level (Glassdoor, Levels.fyi, LinkedIn Salary, BLS)
- Company reputation for compensation
- Role demand trends

| Source | Range | Date |
|--------|-------|------|
| | | |

If no data is available, say so — never invent numbers.

Compare to Aidan's floor ($55K) and target ($65K–$85K). Flag if the role is likely below floor.

---

## Block E — Personalization Plan

Top 5 changes to cv.md for this specific application (keyword injection only — never invent):

| # | Section | Current | Proposed change | Why |
|---|---------|---------|-----------------|-----|
| 1 | | | | |

**Keyword injection rules (from career-ops):**
- JD says "RAG pipelines" and CV says "NLP-driven insights" → reformulate to "NLP pipeline with retrieval"
- JD says "ETL" and CV says "data pipeline" → reformulate to "ETL pipeline"
- Only use vocabulary the JD uses. Never add skills that aren't in cv.md.

---

## Block F — Interview Prep

5–7 likely questions mapped to cv.md proof points. Each question labeled `[inferred from JD]`.

| # | Question | Best proof point from cv.md | Talking point |
|---|----------|----------------------------|---------------|

Include:
- 1–2 likely behavioral questions for a new grad (e.g. "Tell me about a time you had to learn something quickly")
- 1–2 technical questions based on JD requirements
- 1 "background" question: "You're a new grad — why should we hire you over someone with 2 years of experience?" with a recommended frame

---

## Block G — Posting Legitimacy

Assess whether this is a real, active opening. Present signals — not accusations.

**Signals to check:**
1. **Posting freshness** — date posted, apply button state
2. **JD quality** — specific tech/tools named, realistic requirements, role scope defined
3. **Requirement realism** — do years required match the title? Entry-level title + 3 years required = red flag
4. **Company hiring signals** — run WebSearch: `"{company}" layoffs {year}`, `"{company}" hiring freeze`
5. **Reposting** — same role reposted multiple times?

**Three tiers:**
- **High Confidence** — real, active opening
- **Proceed with Caution** — mixed signals
- **Suspicious** — multiple ghost indicators, investigate before investing time

---

## Post-Evaluation

### 1. Save report

Save full evaluation to `data/reports/{###}-{company-slug}-{YYYY-MM-DD}.md`
- `{###}` = next sequential number (zero-padded to 3 digits)
- `{company-slug}` = company name in lowercase with hyphens

### 2. Log to tracker

Update `data/applications.json`. Add fields:
- `archetype`
- `score`
- `reasoning`
- `score_breakdown` (tech_match, seniority_fit)
- `gaps`

Or run: `python agents/scorer.py` to score via Ollama if you want the automated flow.

### 3. Suggest next step

- Score 8+: "Ready to apply. Run `/apply` or open dashboard at http://localhost:8050"
- Score 7: "Borderline. Check Discord briefing or review manually."
- Score below 7: "Below threshold. Skip unless you have a specific reason to apply."
