# Mode: apply — Live Application Assistant

Interactive mode for filling out job application forms. Reads the form, loads existing context, and generates personalized responses for each question.

---

## Workflow

```
1. DETECT   → Identify company + role (from URL, screenshot, or paste)
2. SEARCH   → Find existing report in data/reports/
3. LOAD     → Read report + cv.md + profile.yml
4. ANALYZE  → Identify all visible form questions
5. GENERATE → Personalized response for each question
6. PRESENT  → Formatted responses ready to copy-paste
```

---

## Step 1 — Detect the job

**With Playwright (visible mode):** Take a snapshot of the active page. Read title, URL, visible content.

**Without Playwright:** Ask Aidan to:
- Share a screenshot of the form
- Paste the questions as text
- Or say company + role so we can search for context

---

## Step 2 — Load context

1. Search `data/reports/` for the company name (case-insensitive)
2. If a report exists → load it (archetype, gaps, proof points, score)
3. Read `cv.md` for proof points
4. Read `config/profile.yml` for identity fields (name, email, phone, LinkedIn, GitHub)
5. If no report → offer to run a quick `oferta` evaluation first, or proceed with cv.md only

---

## Step 3 — Analyze form questions

Classify every visible question:

| Type | Examples | Approach |
|------|----------|----------|
| Free text | "Why do you want this role?", cover letter field | Generate from report context + cv.md |
| Identity | Name, email, phone, LinkedIn | Pull from profile.yml |
| Yes/No | "Are you authorized to work in the US?" | Answer from profile.yml |
| Salary | "What are your salary expectations?" | Use $65K–$75K range (or adjust per context) |
| Upload | Resume PDF, cover letter PDF | Note file paths from data/resumes/ and data/cover_letters/ |
| Dropdowns | "How did you hear about this role?", work authorization | Answer factually |

---

## Step 4 — Generate responses

For each free-text question:

1. Check if there's a prior answer in the report (reuse and refine)
2. Use proof points from cv.md mapped to the question's intent
3. Apply career-ops writing rules (specifics over abstractions, no clichés)
4. Match tone to the company's culture signals from the report

**Output format:**

```
## Application Responses: {Company} — {Role}

---

### 1. {Exact form question}
> {Response ready for copy-paste}

### 2. {Next question}
> {Response}
```

---

## Common Questions — Pre-built Frames

**"Why do you want to work here?"**
→ Lead with one specific thing about the company (from report Block A or D), then connect to Aidan's background.

**"Why are you a good fit for this role?"**
→ Match 2–3 JD requirements to cv.md proof points with metrics.

**"Tell us about a relevant project."**
→ Use the most archetype-appropriate project. Include outcome metric.

**"Where do you see yourself in 5 years?"**
→ Data analyst → senior analyst / analytics lead, with actuarial exam path if insurance role.

**Salary field:**
→ Default: "65000" or "$65,000–$75,000" — adjust if market research from report Block D suggests different.

---

## Step 5 — Post-submit

If Aidan confirms the application was submitted:
1. Update `data/applications.json` → set `status: "applied"`, `applied_at: today`
2. Suggest running `/contacto` for LinkedIn outreach to the hiring manager
3. Note follow-up date: +7 days for first follow-up
