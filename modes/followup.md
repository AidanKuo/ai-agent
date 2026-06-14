# Mode: followup — Follow-up Cadence

Track follow-up timing for active applications and generate tailored follow-up messages.

---

## Step 1 — Check active applications

Read `data/applications.json`. Filter for `status: "applied"`. For each:
- Days since `applied_at`
- Whether a follow-up has been sent (check `notes` field or `data/follow-ups.md`)

**Cadence rules:**

| Status | First follow-up | Second follow-up | After 2 attempts |
|--------|----------------|-----------------|-----------------|
| Applied | 7 days after submission | 7 days later | Mark cold, move on |
| Responded (recruiter reply) | Reply within 24h | Every 3 days | No limit |
| Interview | Thank-you same day | Every 3 days | No limit |

---

## Step 2 — Dashboard

Show applications sorted by urgency:

```
Follow-up Dashboard — {date}

| # | Company | Role | Applied | Days | Follow-ups | Urgency |
|---|---------|------|---------|------|------------|---------|
| 1 | ...     | ...  | ...     | ...  | 0          | OVERDUE |
```

Urgency levels:
- **URGENT** — company replied, respond today
- **OVERDUE** — past the 7-day window
- **WAITING** — on track, follow-up scheduled
- **COLD** — 2+ follow-ups sent, no response

---

## Step 3 — Generate follow-up drafts

Generate drafts only for **overdue** and **urgent** entries.

Read `data/reports/` for company context before drafting. If no report, use job data from `data/applications.json`.

### First follow-up (0 prior follow-ups)

3–4 sentence email:
1. Reference specific role + when applied
2. One concrete proof point from cv.md with a metric
3. Soft ask + availability (specific time window)

**Rules:**
- NEVER use: "just checking in", "just following up", "touching base", "circling back"
- Lead with value, not the ask
- Under 150 words
- Reference something specific to that company

**Example:**
```
Subject: Re: Data Analyst Role — Aidan Kuo

Hi [Name or "team"],

I submitted my application for the Data Analyst role on [date]. I wanted to share that my CSV Analyst Bot project reduced manual analysis time by 80% using Python and pandas — closely aligned with the reporting automation work described in the posting.

I'd love to discuss how my background in data pipelines and visualization could contribute to [Company]. Would any time this week work for a brief conversation?

Best,
Aidan Kuo
```

### Second follow-up (1 prior follow-up)

2–3 sentences. Take a **new angle** — don't repeat the first message:
- Share a relevant project update or new completion
- Or reference something recent about the company (new product, blog post)
- Still specific to the role

### Cold (2+ follow-ups, no response)

Don't generate another follow-up. Suggest:
- Mark as `status: "discarded"` in data/applications.json if the role seems filled
- Run `/contacto` to try a different person at the company
- Move on — time is better spent on new applications

---

## Step 4 — LinkedIn alternative

If no email contact is available, use the contacto framework (300 chars max):
- Hook specific to company → proof point → soft ask
- Run `/contacto {company}` to find the right person first

---

## Step 5 — Record sent follow-ups

After Aidan confirms a follow-up was sent, update `data/applications.json`:
- Add to job's `notes` field: `"Follow-up 1 sent {YYYY-MM-DD}"`

If `data/follow-ups.md` exists, append a row:

| # | Date | Company | Role | Channel | Contact | Notes |
|---|------|---------|------|---------|---------|-------|

**Only record follow-ups that were actually sent.**

---

## Step 6 — Summary

```
Follow-up Summary — {date}
- {N} applications being tracked
- {N} overdue — drafts above
- {N} urgent — respond today
- {N} waiting — on track
- {N} cold — consider closing

Review the drafts and tell me which ones you've sent so I can record them.
```
