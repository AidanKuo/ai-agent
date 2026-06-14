# Mode: interview-prep — Interview Intelligence Report

When Aidan has an interview scheduled or wants to prep for a specific company and role, run this mode.

## Inputs

1. **Company name** and **role title** (required)
2. **Evaluation report** in `data/reports/` (if exists) — read for archetype, gaps, matched proof points
3. **cv.md** — read for proof points and talking points
4. **config/profile.yml** — read for candidate context and archetype proof points

---

## Step 1 — Research

Run these searches. Cite sources for every claim. Label inferred questions `[inferred from JD]`.

| Query | What to extract |
|-------|-----------------|
| `"{company} {role} interview questions site:glassdoor.com"` | Actual questions, difficulty, process timeline, offer/reject ratio |
| `"{company} interview process site:teamblind.com"` | Candid process, recent data, hiring bar |
| `"{company} {role} interview site:leetcode.com/discuss"` | Technical topics, round structure |
| `"{company} engineering blog OR data blog"` | Tech stack, values, what they ship |
| `"{company} interview process {role}"` | Prep guides, candidate write-ups |

**Do NOT fabricate questions.** If a source says "they asked about SQL window functions," report that. When generating likely questions from the JD, label them `[inferred from JD]`.

If the company is small with little online data, note that and broaden to similar-stage companies.

---

## Step 2 — Process Overview

```
## Process Overview
- Rounds: {N} rounds, ~{X} days end-to-end
- Format: {e.g., recruiter screen → technical → hiring manager → team}
- Difficulty: {X}/5 (Glassdoor avg, N reviews)
- Positive experience rate: {X}%
- Known quirks: {e.g., "SQL take-home", "no whiteboard — practical only"}
- Sources: {links}
```

---

## Step 3 — Round-by-Round Breakdown

For each discovered round:

```
### Round {N}: {Type}
- Duration: {X} min
- Conducted by: {recruiter / hiring manager / peer / skip-level}
- What they evaluate: {specific skills or traits}
- Reported questions:
  - {question} [source: Glassdoor 2026-Q1]
- How to prepare: {1–2 concrete actions}
```

---

## Step 4 — Likely Questions

### Technical
SQL, Python, data analysis, or tool-specific questions. For each: what they're testing + Aidan's best answer angle (cite cv.md proof point).

### Behavioral
Leadership, problem-solving, collaboration, learning. Map each to a specific story from Aidan's background:
- **DubHacks team lead** → leadership, shipping under pressure, stakeholder communication
- **CSV Analyst Bot** → solving a real problem, building something independently
- **AI Video Game Analysis** → handling large datasets, statistical rigor
- **VetConnect** → user empathy, design thinking, iteration

### New Grad Positioning
Questions that will come up because Aidan is a new grad:
- "You don't have professional experience — why should we hire you?"
  - Frame: Lead with outcomes from projects. "I built X that achieved Y" is professional-quality work.
- "Where do you see yourself in 5 years?"
  - Frame: Honest roadmap — data analyst → senior analyst, with actuarial exam path if insurance role.
- "Tell me about a time you had to learn something new quickly."
  - Frame: Pick a project where you used a new tool (e.g., Streamlit, ArcGIS, or Seaborn for the first time).

### Background Red Flags
Anything the interviewer might probe about Aidan's profile:
- No full-time work history → address proactively with project outcomes
- GIS major applying to data roles → explain how geography + data science = unique perspective on spatial data
- Actuarial exams not yet passed → frame as commitment + trajectory, not failure

---

## Step 5 — Technical Prep Checklist

Based on what the company actually tests — not generic advice:

```
- [ ] {topic} — why: "{evidence from research}"
- [ ] {topic} — why: "{their job posting requires it}"
```

Max 10 items. Prioritize by frequency in research + relevance to role.

---

## Step 6 — Company Signals

- **Values they screen for:** name them, cite source
- **Vocabulary to use:** terms the company uses internally (shows homework)
- **Things to avoid:** anti-patterns flagged in interview reviews
- **Questions to ask them:** 2–3 sharp questions tied to recent news or blog posts

---

## Output

Save full report to `data/reports/{company-slug}-{role-slug}-interview-prep.md`:

```markdown
# Interview Prep: {Company} — {Role}
**Researched:** {YYYY-MM-DD}
**Sources:** {N} Glassdoor reviews, {N} Blind posts, {N} other
```

---

## Post-Prep

After delivering the report:
1. Ask if Aidan wants to practice answering any of the questions out loud (simulate the interview)
2. Suggest running `deep` mode if company research was thin
3. If interview is scheduled, note: "Your interview is in {X} days. Want a 24-hour reminder review?"
