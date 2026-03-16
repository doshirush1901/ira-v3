# Anu — AI Recruiter Agent

Anu is the AI Recruiter in the Ira Pantheon. **Engagement is via Rushabh's email only** (no Lovable or external UI): Anu and other agents draft replies; sending goes through Gmail as configured for the Ira mailbox. Applicant datasheets are stored in a **candidate database** (SQLite) built from fragmented files in `data/imports/22_HR Data` and (optionally) from the Recruitment CVs mailbox.

Anu supports:

1. **Resume & profile ingestion** — PDF or plain text → structured JSON (name, contact, skills, experience, education).
2. **Candidate scoring** — 1–5 score + label (Strong/Medium/Low Fit) + rationale, with optional job description.
3. **Mentor-style chat** — Career coach persona; answers recruiter or candidate questions using the candidate’s profile and chat history.
4. **Profile export** — Recruiter-ready summary text; optional PDF download (when PdfCo is configured).

All endpoints require the Ira API server to be running and the Pantheon (including Anu) to be initialised.

---

## 22_HR Data folder (imports)

The folder `data/imports/22_HR Data` contains HR docs that Anu uses for context when scoring and exporting:

- **Org structure**, **Recruitment Strategy** (e.g. CAD/Tool Design Engineer, Automotive Mumbai), **HR Machinecraft 2025**, **Mock Test Detailed**, **Our Struggle in Plastics**, **2026 SALARY SHEET** — these inform role fit and company context.
- **Job Application (Responses).xlsx**, **CAD candidate.xlsx**, **Shortlisted candidates update.xlsx** (sheet "list": NAME, MAIL ID, DESIGNATION, STATUS) — candidate data used to **build the candidate database**. All three are merged by email in `build_candidate_database_from_imports.py`.

To make 22_HR Data searchable for Anu:

1. Run **`ira index-imports`** so the imports metadata index includes these files.
2. Run a **full ingestion** (or ingest that folder) so the knowledge base (Qdrant) has chunks from the PDFs/XLSXs. Then `get_hr_recruitment_context()` will pull relevant snippets when scoring/exporting.

To **build the candidate database** from 22_HR Data spreadsheets:

```bash
poetry run python scripts/build_candidate_database_from_imports.py
```

This reads `Job Application (Responses).xlsx`, `CAD candidate.xlsx`, and `Shortlisted candidates update.xlsx` (sheet "list"), maps rows to candidate profiles, merges by email, and upserts into `data/brain/candidates.db`. Use `--dry-run` to preview. After that, **GET /api/anu/candidates** and **GET /api/anu/candidates/by-email?email=...** return applicant datasheets for use when drafting emails to applicants.

---

## Recruitment knowledge stack (data/knowledge)

Curated files used for Stage 1/2 drafting and runbook (Cursor or Ira):

| File | Purpose |
|------|--------|
| `recruitment_company_intro_warm.txt` | Warm company intro (who we are, what we do, location Umargam). Used as `company_intro_short` in Stage 2. |
| `recruitment_open_positions.md` | Current open positions (CAD, Production Planning, Plant Manager, etc.) at Umargam. Passed as part of `job_description_or_context` so drafts align with openings. |
| `recruitment_cad_jd.md` | CAD / Tool Design Engineer role requirements. Used in `job_description_or_context` when drafting for CAD candidates. |
| `recruitment_company_story_our_struggle.txt` | Short "Our Struggle in Plastics" company story; optional 1–2 sentences in drafts for warmth. |
| `recruitment_case_study_generic.md`, `plant_manager_case_study_22014_ALP_Delhi.md` | Role-specific case studies for Stage 2. |
| `recruitment_dice_questions.md` | DICE (behavioural) questions per role (Default, Plant Manager, CAD, PLC, Procurement, CAM). |

**Stage 2 draft API** (`POST /api/anu/draft-recruitment-stage2`) accepts optional **`job_description_or_context`**: concatenate open positions + role-specific JD (e.g. CAD) from the table above; scripts `send_recruitment_emails_one_by_one.py`, `recruitment_drip_campaign.py`, and `redraft_one_candidate.py` build this from these knowledge files and pass it so the LLM tailors the role description to current openings.

---

## API Endpoints

Base URL: `http://localhost:8000` (or your deployed URL).

### 1. Parse resume (PDF upload)

```http
POST /api/anu/parse-resume
Content-Type: multipart/form-data
file: <PDF file>
```

**Response:** `{"candidate_profile": { ... }}` — structured profile (name, email, phone, location, current_role, skills, experience_years, education, summary, experience_highlights).

### 2. Parse resume (plain text)

```http
POST /api/anu/parse-resume-text
Content-Type: application/json
{"resume_text": "Full resume text here..."}
```

**Response:** `{"candidate_profile": { ... }}`.

### 3. List / get candidates (applicant datasheets)

```http
GET /api/anu/candidates?limit=100&offset=0
GET /api/anu/candidates/by-email?email=design.suraj91@gmail.com
```

**Response (list):** `{"total": N, "candidates": [{ "email", "name", "profile", "score", "source_type", "source_id", "updated_at" }, ...]}`.  
**Response (by-email):** Single candidate object or 404.

### 4. Score candidate

```http
POST /api/anu/score
Content-Type: application/json
{
  "candidate_profile": { ... },
  "job_description": "Optional JD text; omit for general employability score."
}
```

**Response:** `{"score": {"score": 4.0, "label": "Strong Fit", "rationale": "...", "strengths": [...], "gaps": [...]}}`.

### 5. Mentor chat

```http
POST /api/anu/chat
Content-Type: application/json
{
  "candidate_profile": { ... },
  "message": "What are this candidate's strengths?",
  "conversation_history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

**Response:** `{"reply": "Anu's reply text"}`.

### 6. Export profile (text or PDF)

```http
POST /api/anu/export
Content-Type: application/json
{
  "candidate_profile": { ... },
  "scoring": { ... },
  "format": "text"
}
```

- `format`: `"text"` (default) or `"pdf"`.
- **Response (text):** `{"format": "text", "summary": "..."}`.
- **Response (pdf):** `application/pdf` body with `Content-Disposition: attachment; filename=candidate_profile.pdf` (when PdfCo is available).

---

## Candidate database and email engagement

- **Candidate store:** SQLite at `data/brain/candidates.db`. Built from 22_HR Data XLSXs via `scripts/build_candidate_database_from_imports.py`. Optional: add candidates from Recruitment CVs mailbox.
- **List/get candidates:** `GET /api/anu/candidates`, `GET /api/anu/candidates/by-email?email=...`. Use when drafting replies so the draft has full applicant datasheet context.
- **Engagement:** All applicant communication goes through **Rushabh's email** (Gmail as configured for Ira). No Lovable or external UI: use `POST /api/email/draft` or the task/query pipeline with candidate profile from the DB; then `POST /api/email/send` only when the user explicitly says to send.
- **Export:** “Export profile” button → `POST /api/anu/export` with `format: "pdf"`; use the PDF response as download or link.


---

## Recruitment drive (drip campaign)

For a **recruitment drive** that re-engages all candidates with a drip (intro → role-based assessment), see **`docs/RECRUITMENT_DRIVE_DRIP.md`**. That doc defines:

- **Stage 1:** Company intro (who we are, location Umargam, what we do, machines, markets, production process, role, how it fits, key things, location).
- **Stage 2:** Per-candidate email with role-specific **case study**, **DICE (short)**, and **skills/software questions** drawn from their **CV**.
- **CV pipeline:** Download CV from Gmail (search by candidate email, thread with attachments) or from `data/imports/22_HR Data` → extract text → parse via `POST /api/anu/parse-resume-text` (or parse-resume) → store parsed profile via `PATCH /api/anu/candidates/by-email` → use to draft detailed, personalised Stage 2 emails. Drafts are shown in Cursor; send only on explicit instruction.
- **Run the recruitment drip:** From repo root, with the API server running: `poetry run python scripts/recruitment_drip_campaign.py`. Use `--stage cv_only` to only fetch/parse CVs; `--stage stage1` or `stage2` to only generate drafts; `--output-dir` for draft output (default `data/recruitment_drafts`).

Error responses use HTTP 4xx/5xx with `detail` string. On 503 (“Anu agent not available”), ensure the Ira server has started fully and the Pantheon includes Anu.
