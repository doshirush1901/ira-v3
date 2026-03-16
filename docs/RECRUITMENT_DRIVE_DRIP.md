# Recruitment drive — Drip model and CV-backed email drafting

This document defines the **recruitment drip campaign** for re-engaging candidates in the candidate database (`data/brain/candidates.db`). The flow: **Stage 1** = company intro (same structure for all); **Stage 2** = per-candidate, role-based email using **CV context** (download → scan → parse via LLM → draft detailed email). All engagement is via Rushabh's email; drafts are shown in Cursor and sent only on explicit instruction.

---

## 1. Drip model (overview)

| Stage | Content | Audience |
|-------|--------|----------|
| **1. Re-engage intro** | Company intro (who we are, location, what we do, machines, markets, production process, role we’re looking for, how role fits, key things in role, location Umargam). Single short email to open the conversation. | All candidates (or filtered by role) |
| **2. Role + assessment** | Per-candidate email: role-specific **case study**, **DICE (short)**, and **skills/software questions** drawn from their **CV**. CV is downloaded (Gmail or 22_HR Data), parsed with LLM (Anu), then used to personalise questions and draft. | One email per candidate, personalised |

**CV pipeline (required for Stage 2):** For each candidate we need CV context. Steps:

1. **Locate CV** — Prefer Gmail: search by `from:<candidate_email>` (optionally `label:"Recruitment CVs"`), take first thread that has a PDF/DOCX attachment; alternatively use a file in `data/imports/22_HR Data` if CVs are stored there by email/name.
2. **Download / extract** — If Gmail: call `GET /api/email/thread/{thread_id}/with-attachments` to get attachment text; if file: read and extract text (PDF/DOCX).
3. **Parse via LLM** — Send extracted text to `POST /api/anu/parse-resume-text` (or `parse-resume` for PDF bytes). Get structured `candidate_profile` (skills, software, experience, education, summary).
4. **Merge and store** — Optionally merge parsed fields into the candidate row in `candidates.db` (e.g. `profile_json` or a dedicated `cv_parsed_json` column) so Anu and draft logic have one place to read from.
5. **Draft Stage 2 email** — Use: company intro (abbreviated if already sent in Stage 1), **role** (from profile `current_role`), **role-specific case study** (from knowledge base), **short DICE questions** (2–4 behavioural), **skills/software questions** that explicitly reference software/tools they mentioned in their CV. Draft is detailed and personalised; show in Cursor for review/send.

---

## 2. Stage 1 — Company intro (re-engage)

Use this block (or a short version) in the first touch so every candidate gets the same context. Source of truth: company docs, `data/knowledge/`, `data/imports/`; keep wording consistent and factual.

- **Who we are:** Machinecraft Technologies — we design and build industrial thermoforming and related machinery.
- **Where we are located:** Umargam (and Mumbai). The role we are recruiting for is based at **Umargam**.
- **What we do:** We engineer and manufacture thermoforming machines (e.g. PF1, PF2, IMG, UNO, FCS, AM series) and support customers through design, build, FAT, installation, and service.
- **What machines we make:** PF1 (single-station vacuum forming, various sizes), PF2, IMG (in-mold graining), UNO, FCS, AM series. Sizes from ~1×1.5 m to 5×2.8 m forming area; sheet thickness 2–12 mm typical; options include autoloader, universal frames, central cooling, PLC/HMI control.
- **Markets we serve:** Automotive (India, EU), packaging, fire-safety (e.g. UAE), industrial trays, signage, hydroponics, and other thermoforming applications. Customers in India, UAE, UK, Germany, Netherlands, Canada, Russia, USA, etc.
- **Typical production process:** BOM freeze → procurement (Order/Receive/Send/Back-Return) → fabrication (cutting, welding) → fitting (FT) → assembly → electrical → testing (FAT) → punch list → dispatch. Coordination between Production, Procurement, CAD/CAM, Factory Head, and Sales. Task codes and gates (e.g. Asana) used for tracking.
- **Role we are looking for:** [Varies by campaign — e.g. CAD/Tool Design Engineer, Production Planning, Plant Manager, PLC Programming, Procurement, etc. Can be multi-role; list the ones relevant to this drive.]
- **How that role fits:** E.g. CAD fits into design and drawing release before fabrication; Production Planning fits into sequencing and coordination; Plant Manager fits into shop-floor and cross-functional coordination at Umargam.
- **Key things in the role:** [2–4 bullets per role from HR/recruitment docs.]
- **Location of role:** Umargam.

**Format:** One concise email (plain text, mobile-friendly). No pipe tables in body. One clear CTA (e.g. “If you’re still interested, reply with a short note and we’ll send role-specific next steps.”).

---

## 3. Stage 2 — Role-based case study, DICE, and skills (per candidate)

After Stage 1 (or in parallel if we skip intro for some), send **one detailed email per candidate** that includes:

### 3.1 Role-specific case study

- **Source:** Use existing case studies where they exist (e.g. `data/knowledge/plant_manager_case_study_22014_ALP_Delhi.md` for Plant Manager / Production Planning). For other roles (CAD, PLC, Procurement, CAM), create or select a short scenario that mirrors real Machinecraft process (BOM, procurement, fabrication, fitting, dispatch).
- **Content:** Project code, customer, machine type, current state (BOM, procurement, fabrication, fitting, people), and a clear “Your task” in 200–300 words.
- **Personalisation:** Address the candidate by name and state the **role** we’re considering them for (from `profile.current_role` or application form).

### 3.2 DICE test (short)

- **Purpose:** Short behavioural/cultural-fit questions (no long psychometric).
- **Format:** 2–4 questions, e.g.:
  - A situation where they had to give difficult feedback or prioritise between stakeholders.
  - How they act under pressure (dispatch date vs quality/safety).
  - A time they learned something new quickly to unblock work.
  - One thing they’re proud of that wasn’t about hitting a target.
- **Source:** Reuse or adapt from `data/knowledge/draft_email_harshul_jain_plant_manager_umargam.md` (Parts A/B) per role.

### 3.3 Skills and software (from CV)

- **Rule:** Only ask about software/tools/skills **they have mentioned in their CV**. Do not invent or assume.
- **Process:** Use the **parsed CV** from Step 3–4 of the CV pipeline (`skills`, `experience_highlights`, `summary`). From that, pick 2–4 concrete items (e.g. “You mentioned experience with SolidWorks and AutoCAD — can you describe a recent project where you used both?” or “Your CV mentions PLC programming — which platforms have you used on the shop floor?”).
- **Draft:** Questions must be explicit and specific to their stated experience so the email feels tailored and shows we read their CV.

### 3.4 Drafting the Stage 2 email

- **Inputs:** Candidate name, email, `profile` (from DB), **parsed CV** (from Anu after download/parse), **role** (e.g. CAD, Production Planning, Plant Manager), **case study text** (from knowledge), **DICE questions** (from prompt or template), **skills/software questions** (generated from parsed CV), **company_intro_short** (from `recruitment_company_intro_warm.txt`), **job_description_or_context** (optional: open positions + role-specific JD from `recruitment_open_positions.md` and e.g. `recruitment_cad_jd.md`).
- **Output:** One email: greeting → brief context (company + role at Umargam) → case study (full or linked) → DICE (short) → skills/software questions → CTA (reply with answers by date).
- **Voice:** Professional, warm, Rushabh/HR tone. No fabrication of specs, dates, or compensation. Per `ira-email-safety.mdc`: draft only; send only on explicit user instruction.
- **Job context:** Scripts build `job_description_or_context` from `data/knowledge/recruitment_open_positions.md` and, for CAD candidates, `recruitment_cad_jd.md`, so the role description in the email aligns with current openings and requirements.

---

## 3.5 Recruitment knowledge stack (22_HR Data → KB)

To make HR docs (Recruitment Strategy, Org Structure, Our Struggle in Plastics, etc.) searchable for Anu and Stage 2 drafting:

1. **Index** (so the metadata index includes 22_HR Data files):
   ```bash
   poetry run ira index-imports
   ```
   Use `--no-llm` for a faster index without LLM summaries.

2. **Ingest** (chunk and embed 22_HR Data into Qdrant so retrieval works):
   ```bash
   poetry run ira ingest --include-prefix "22_HR Data" --force
   ```
   This ingests only files under `data/imports/22_HR Data/` (PDFs and, if supported, XLSX). After this, `get_hr_recruitment_context()` and any role-specific retrieval can pull from these docs.

3. **Candidate DB** (all three sheets: Job Application, CAD candidate, Shortlisted list):
   ```bash
   poetry run python scripts/build_candidate_database_from_imports.py
   ```

4. **Curated knowledge files** (used by Stage 2 scripts and draft API):
   - `data/knowledge/recruitment_company_intro_warm.txt` — company intro for drafts.
   - `data/knowledge/recruitment_open_positions.md` — open positions (CAD, Production Planning, Plant Manager, etc.); passed as part of `job_description_or_context`.
   - `data/knowledge/recruitment_cad_jd.md` — CAD role requirements; used in `job_description_or_context` for CAD candidates.
   - `data/knowledge/recruitment_company_story_our_struggle.txt` — optional short company story for warmth.

---

## 4. CV pipeline — Technical steps

### 4.1 Where CVs come from

| Source | How | When to use |
|--------|-----|-------------|
| **Gmail (Recruitment CVs)** | `POST /api/email/search` with `from_address=<candidate_email>`, optional `query` or label so results are from “Recruitment CVs”. From results, take a thread that has attachments; call `GET /api/email/thread/{thread_id}/with-attachments` to get PDF/DOCX text. | Primary when candidates have applied via email and CV was attached. |
| **22_HR Data folder** | If CVs are saved under `data/imports/22_HR Data/` (e.g. by name or email), read file and extract text (pypdf for PDF, python-docx for DOCX). | When HR has already downloaded and filed CVs. |
| **Candidate DB only** | If no CV file or thread found, use only `profile_json` from `candidates.db` (from Job Application / CAD candidate sheets). Stage 2 can still send case study + DICE but **omit or generalise** software questions (no “you mentioned X in your CV”). | Fallback when no CV is available. |

### 4.2 Parse and store

- **Parse:** `POST /api/anu/parse-resume-text` with `resume_text` = extracted CV text (or `POST /api/anu/parse-resume` with PDF file). Response: `candidate_profile` (name, email, phone, current_role, skills, experience_years, education, summary, experience_highlights).
- **Store:** Either (a) merge into existing `profile_json` for that candidate and `UPDATE candidates SET profile_json = ?, updated_at = ? WHERE email = ?`, or (b) add a column `cv_parsed_json` and store the parsed profile there so we keep application-sheet data separate from CV-parsed data. Draft logic then uses both.

### 4.3 Script / API outline

1. **List candidates** — `GET /api/anu/candidates?limit=500` (or read `candidates.db` directly).
2. **For each candidate (email, name, profile):**
   - Try **Gmail:** search with `from_address=candidate_email`, optionally label “Recruitment CVs”. If a thread has attachments, get thread with `with-attachments`, concatenate attachment texts (prioritise PDF/DOCX), take first substantial block (e.g. first 20k chars).
   - Else try **22_HR Data:** look for file matching email or name; extract text.
   - If CV text found: call **Anu parse-resume-text**, then **update** candidate (profile merge or cv_parsed_json).
   - If no CV: mark “no_cv” for this candidate; Stage 2 draft will use only DB profile and no CV-specific software questions.
3. **Generate Stage 1 draft** — One shared draft (or per-role variant) with company intro; optionally batch for review in Cursor.
4. **Generate Stage 2 drafts** — For each candidate with at least role + (parsed CV or profile): run draft logic with case study + DICE + skills-from-CV; output one draft per candidate (e.g. in a table or one file per candidate). Present in Cursor for review; send only when user says “send”.

### 4.4 Run the recruitment drip script

The script **`scripts/recruitment_drip_campaign.py`** implements the full pipeline. **Requires the Ira API server to be running.**

```bash
# From repo root
poetry run python scripts/recruitment_drip_campaign.py
```

**CLI options:** `--base-url`, `--label` (Gmail label, default "Recruitment CVs"), `--no-label` (search all mail by from: so threads like Suraj's are found even if not in that label), `--save-cvs-to` (dir path, e.g. `data/recruitment_cvs` — download PDF/DOCX attachments there, one subdir per candidate email), `--limit`, `--stage`, `--output-dir`, `--role-focus`, `--cta`, `--dry-run`.

**Output files:** `{output-dir}/stage1_intro.md` (company intro); `{output-dir}/stage2_{sanitized_email}.md` (per-candidate draft). CV-parsed data is stored via `PATCH /api/anu/candidates/by-email`.

---

## 5. Roles and case-study mapping

| Role / area | Case study / scenario | DICE (short) | Skills from CV |
|-------------|----------------------|--------------|----------------|
| Plant Manager / Production Planning | `plant_manager_case_study_22014_ALP_Delhi.md` (PF1 delayed procurement, fitting blocked) | Feedback, prioritisation, pressure, learning, pride | Not applicable (process/people focus) or tools they mentioned |
| CAD / Design Engineer | Scenario: drawing release delay blocking fabrication; BOM change mid-stream | Same style; add “how do you handle last-minute drawing changes?” | SolidWorks, AutoCAD, Creo, etc. from parsed CV |
| PLC Programming | Scenario: HMI/PLC integration delay before FAT | Pressure, learning new platform, coordination with electrical | PLC platforms, HMI, from parsed CV |
| Procurement | Scenario: critical component late; alternate vendor | Stakeholder prioritisation, pressure, communication | ERP, Excel, vendor management from parsed CV |
| CAM | Scenario: program release and machine readiness | Learning new CAM software, coordination with shop floor | CAM software from parsed CV |

Case studies for CAD, PLC, Procurement, CAM can be added under `data/knowledge/` (e.g. `recruitment_case_study_cad.md`) and referenced here.

---

## 6. Summary

- **Stage 1:** One short company intro (who we are, location Umargam, what we do, machines, markets, production process, role, how it fits, key things, location). Same structure for all; optional per-role tweak.
- **Stage 2:** Per-candidate detailed email: role-specific case study + short DICE + skills/software questions **only from their CV**. CV must be downloaded (Gmail or 22_HR Data), scanned, parsed via LLM (Anu), then used to draft.
- **CV pipeline:** Gmail search by candidate email → thread with attachments → extract text → Anu parse → store → use in Stage 2 draft. If no CV, use DB profile only and omit CV-specific software questions.
- **Delivery:** All drafts shown in Cursor; send only on explicit user instruction. No auto-send.

**Cursor / Ira runbook (recruitment):**
- Start Ira (Docker + stack) if needed; ensure API server is running for scripts that call `/api/anu/draft-recruitment-stage2` and `/api/anu/candidates`.
- Index and ingest 22_HR Data (section 3.5); build candidate DB (section 3.5 step 3). Then run `recruitment_drip_campaign.py` or `send_recruitment_emails_one_by_one.py`; drafts go to `data/recruitment_drafts/`. Redraft one candidate: `poetry run python scripts/redraft_one_candidate.py <email>`.
- All drafts are shown in Cursor; send only on explicit user instruction.

**Confidence:** High (design). **Freshness:** Current. **Sources:** `docs/ANU_AI_RECRUITER.md`, `docs/RECRUITMENT_DRIVE_DRIP.md`, `data/knowledge/recruitment_company_intro_warm.txt`, `data/knowledge/recruitment_open_positions.md`, `data/knowledge/recruitment_cad_jd.md`, `data/knowledge/plant_manager_case_study_22014_ALP_Delhi.md`, `src/ira/interfaces/server.py`, `src/ira/agents/anu.py`.
