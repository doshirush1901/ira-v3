#!/usr/bin/env python3
"""
Recruitment drip campaign: fetch CVs (Gmail / 22_HR Data), parse via Anu, store,
then generate Stage 1 (company intro) and Stage 2 (per-candidate) email drafts.

Requires: Ira API server running (Gmail, Anu, candidates API).
Usage:
  poetry run python scripts/recruitment_drip_campaign.py
  poetry run python scripts/recruitment_drip_campaign.py --stage cv_only --limit 5
  poetry run python scripts/recruitment_drip_campaign.py --stage stage2 --output-dir data/recruitment_drafts --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_KNOWLEDGE = PROJECT_ROOT / "data" / "knowledge"
HR_DATA_DIR = PROJECT_ROOT / "data" / "imports" / "22_HR Data"

# Role normalization: profile.current_role (or comma-separated) -> key for case study / DICE
ROLE_TO_KEY = {
    "plant manager": "plant_manager",
    "production planning": "production_planning",
    "production plan": "production_planning",
    "cad": "cad",
    "design engineer": "cad",
    "mechanical design": "cad",
    "plc": "plc",
    "procurement": "procurement",
    "cam": "cam",
    "other": "default",
}


def _normalize_role(role_str: str) -> str:
    """Map current_role string to a key (plant_manager, production_planning, cad, plc, procurement, cam, default)."""
    if not (role_str or "").strip():
        return "default"
    r = role_str.strip().lower()
    # Take first token if comma-separated (e.g. "CAD, Production Planning" -> "cad")
    first = r.split(",")[0].strip().lower()
    for k, v in ROLE_TO_KEY.items():
        if k in first or k in r:
            return v
    return "default"


def _case_study_path(role_key: str) -> Path:
    """Path to case study markdown for this role."""
    if role_key in ("plant_manager", "production_planning"):
        return DATA_KNOWLEDGE / "plant_manager_case_study_22014_ALP_Delhi.md"
    return DATA_KNOWLEDGE / "recruitment_case_study_generic.md"


def _load_dice_questions(role_key: str) -> str:
    """Load DICE questions for role from recruitment_dice_questions.md; fallback to default set."""
    path = DATA_KNOWLEDGE / "recruitment_dice_questions.md"
    if not path.exists():
        return (
            "1. Describe a time when you had to give difficult feedback. How did you approach it?\n"
            "2. When stakeholders pull in different directions, how do you prioritise and communicate?\n"
            "3. What do you do when under pressure to meet a deadline and quality would be compromised?\n"
            "4. What's one thing you're proud of that wasn't about hitting a target?"
        )
    text = path.read_text(encoding="utf-8")
    # Parse sections: ## Default set, ## Plant Manager, ## CAD, etc.
    section_by_role = {
        "default": "Default set",
        "plant_manager": "Plant Manager",
        "production_planning": "Plant Manager",
        "cad": "CAD",
        "plc": "PLC Programming",
        "procurement": "Procurement",
        "cam": "CAM",
    }
    title = section_by_role.get(role_key, "Default set")
    in_section = False
    lines = []
    for line in text.splitlines():
        if line.startswith("## ") and title in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            if line.strip() and (line[0].isdigit() or line.strip().startswith("-")):
                lines.append(line)
    if lines:
        return "\n".join(lines)
    # Fallback: use numbered items from Default set
    for line in text.splitlines():
        if line.startswith("## Default set"):
            in_section = True
            continue
        if in_section and line.strip() and line[0].isdigit():
            lines.append(line)
        if in_section and line.startswith("## ") and "Default" not in line:
            break
    return "\n".join(lines) if lines else "1. Describe a time you gave difficult feedback.\n2. How do you prioritise when stakeholders disagree?"


# --- HTTP helpers (API) ---


def _api_get(base_url: str, path: str, timeout: int = 60) -> dict | list:
    import urllib.request
    req = urllib.request.Request(f"{base_url.rstrip('/')}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _api_post(base_url: str, path: str, data: dict, timeout: int = 90) -> dict:
    import urllib.request
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _api_patch(base_url: str, path: str, data: dict, timeout: int = 30) -> dict:
    import urllib.request
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _email_search(base_url: str, from_address: str, label: str = "", max_results: int = 5) -> list[dict]:
    payload = {"from_address": from_address, "max_results": max_results}
    if label:
        payload["label"] = label
    data = _api_post(base_url, "/api/email/search", payload, timeout=60)
    return data.get("emails", [])


def _thread_with_attachments(
    base_url: str,
    thread_id: str,
    max_attachment_chars: int = 50000,
    save_to_dir: str | None = None,
    from_email: str | None = None,
) -> list[dict]:
    from urllib.parse import quote
    path = f"/api/email/thread/{thread_id}/with-attachments?max_attachment_chars={max_attachment_chars}"
    if save_to_dir and from_email:
        path += f"&save_to_dir={quote(save_to_dir, safe='')}&from_email={quote(from_email, safe='')}"
    try:
        data = _api_get(base_url, path, timeout=90)
        return data.get("messages", [])
    except Exception:
        data = _api_get(base_url, f"/api/email/thread/{thread_id}", timeout=30)
        return data.get("messages", [])


def _extract_cv_text_from_messages(messages: list[dict], max_chars: int = 20000) -> str:
    """Concatenate first substantial attachment text from thread messages."""
    for m in messages:
        for t in m.get("attachment_texts", []):
            if t and len(t.strip()) > 200:
                return t.strip()[:max_chars]
    return ""


def _parse_resume_text(base_url: str, resume_text: str) -> dict | None:
    try:
        out = _api_post(base_url, "/api/anu/parse-resume-text", {"resume_text": resume_text}, timeout=60)
        return out.get("candidate_profile")
    except Exception:
        return None


def _update_cv_parsed(base_url: str, email: str, candidate_profile: dict) -> bool:
    from urllib.parse import quote
    try:
        _api_patch(
            base_url,
            f"/api/anu/candidates/by-email?email={quote(email, safe='')}",
            {"candidate_profile": candidate_profile},
            timeout=30,
        )
        return True
    except Exception:
        return False


def _extract_text_from_file(file_path: Path, max_chars: int = 20000) -> str:
    """Extract text from PDF or DOCX file."""
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
            return text[:max_chars]
        if suffix in (".docx", ".doc"):
            from docx import Document
            doc = Document(file_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            return text[:max_chars]
    except Exception:
        pass
    return ""


def _find_cv_in_hr_data(email: str, name: str | None) -> Path | None:
    """Look for a PDF/DOCX in 22_HR Data whose filename contains email local part or normalized name."""
    if not HR_DATA_DIR.exists():
        return None
    local_part = email.split("@")[0].lower() if email else ""
    name_tokens = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).split()[:3]
    for f in HR_DATA_DIR.iterdir():
        if f.suffix.lower() not in (".pdf", ".docx", ".doc"):
            continue
        stem = f.stem.lower()
        if local_part and local_part in stem:
            return f
        for tok in name_tokens:
            if len(tok) > 2 and tok in stem:
                return f
    return None


def _skills_questions_from_cv(cv_parsed: dict) -> str:
    """Build 2–4 questions referencing only skills/tools from parsed CV."""
    skills = cv_parsed.get("skills") or []
    highlights = cv_parsed.get("experience_highlights") or []
    if not skills and not highlights:
        return "(No specific skills questions — CV had no tools/skills listed.)"
    # Prefer software/tools (SolidWorks, AutoCAD, PLC, etc.)
    tools = [s for s in skills if s and len(s) > 2][:4]
    if not tools:
        return "Based on your experience, describe a recent project relevant to this role."
    if len(tools) == 1:
        return f"You mentioned experience with {tools[0]}. Can you describe a recent project where you used it?"
    return (
        f"You mentioned experience with {', '.join(tools[:2])}. "
        "Can you describe a recent project where you used these (or similar) and how you applied them?"
    )


def _job_description_or_context(role_key: str) -> str:
    """Build role/position context from recruitment_open_positions.md and role-specific JD (e.g. CAD)."""
    parts = []
    open_path = DATA_KNOWLEDGE / "recruitment_open_positions.md"
    if open_path.exists():
        parts.append(open_path.read_text(encoding="utf-8").strip())
    if role_key == "cad":
        cad_path = DATA_KNOWLEDGE / "recruitment_cad_jd.md"
        if cad_path.exists():
            parts.append(cad_path.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts) if parts else ""


def _load_stage1_template(role_focus: str, cta: str) -> str:
    path = DATA_KNOWLEDGE / "recruitment_stage1_intro_template.txt"
    if not path.exists():
        return f"Subject: Re: Your application\n\n[ROLE_FOCUS]: {role_focus}\n\n{cta}"
    text = path.read_text(encoding="utf-8")
    return text.replace("[ROLE_FOCUS]", role_focus).replace("[CTA]", cta)


def _draft_stage2(
    base_url: str,
    candidate_name: str,
    role: str,
    case_study_text: str,
    dice_questions: str,
    skills_questions: str,
    company_intro_short: str,
    job_description_or_context: str = "",
) -> dict[str, str] | None:
    try:
        out = _api_post(
            base_url,
            "/api/anu/draft-recruitment-stage2",
            {
                "candidate_name": candidate_name,
                "role": role,
                "case_study_text": case_study_text,
                "dice_questions": dice_questions,
                "skills_questions": skills_questions,
                "company_intro_short": company_intro_short,
                "job_description_or_context": job_description_or_context,
            },
            timeout=120,
        )
        return out
    except Exception:
        return None


async def run_cv_pipeline(
    base_url: str,
    candidates: list[dict],
    label: str,
    dry_run: bool,
    save_cvs_to: str | None = None,
) -> dict[str, dict]:
    """For each candidate: try Gmail then 22_HR Data; parse and store CV. Returns report {email: {cv_source, cv_stored}}.
    If save_cvs_to is set, PDF/DOCX attachments are downloaded to save_cvs_to / sanitized(email) / when fetching from Gmail.
    """
    report = {}
    for c in candidates:
        email = (c.get("email") or "").strip().lower()
        name = c.get("name") or ""
        if not email or "@" not in email:
            continue
        cv_source = "none"
        cv_stored = False
        cv_text = ""

        # 1) Gmail (label optional: use "" to search all mail so we find threads like Suraj's)
        try:
            emails = _email_search(base_url, email, label=label, max_results=5)
            for e in emails:
                thread_id = e.get("thread_id")
                if not thread_id:
                    continue
                messages = _thread_with_attachments(
                    base_url,
                    thread_id,
                    save_to_dir=save_cvs_to,
                    from_email=email if save_cvs_to else None,
                )
                cv_text = _extract_cv_text_from_messages(messages)
                if cv_text:
                    cv_source = "gmail"
                    break
        except Exception:
            pass

        # 2) 22_HR Data fallback
        if not cv_text:
            hr_file = _find_cv_in_hr_data(email, name)
            if hr_file:
                cv_text = _extract_text_from_file(hr_file)
                if cv_text:
                    cv_source = "22_hr_data"

        # 3) Parse and store
        if cv_text and not dry_run:
            profile = _parse_resume_text(base_url, cv_text)
            if profile:
                cv_stored = _update_cv_parsed(base_url, email, profile)

        report[email] = {"cv_source": cv_source, "cv_stored": cv_stored}
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recruitment drip: fetch CVs, parse, store, generate Stage 1 and Stage 2 drafts.",
    )
    parser.add_argument("--base-url", default=os.environ.get("IRA_API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--label", default="Recruitment CVs", help="Gmail label for CV search (use empty with --no-label)")
    parser.add_argument("--no-label", action="store_true", help="Search all mail by from: (no label); finds threads like Suraj's even if not in Recruitment CVs")
    parser.add_argument("--save-cvs-to", default="", help="Download PDF/DOCX attachments to this dir (e.g. data/recruitment_cvs); subdir per candidate email")
    parser.add_argument("--limit", type=int, default=500, help="Max candidates to process")
    parser.add_argument(
        "--stage",
        choices=("cv_only", "stage1", "stage2", "all"),
        default="all",
        help="Run only CV pipeline, only Stage 1, only Stage 2, or all",
    )
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "data" / "recruitment_drafts"))
    parser.add_argument("--role-focus", default="CAD, Production Planning, Plant Manager, PLC, Procurement, CAM")
    parser.add_argument("--cta", default="If you're still interested, reply with a short note and we'll send role-specific next steps.")
    parser.add_argument("--dry-run", action="store_true", help="No writes, no API updates")
    args = parser.parse_args()

    # 1) Load candidates
    try:
        data = _api_get(args.base_url, f"/api/anu/candidates?limit={args.limit}&offset=0")
    except Exception as e:
        err = str(e)
        if "404" in err:
            print(
                f"Got 404 from {args.base_url}. Start the Ira API server first:\n"
                "  poetry run uvicorn ira.interfaces.server:app --host 0.0.0.0 --port 8000\n"
                "Then run this script again.",
                file=sys.stderr,
            )
        else:
            print(f"Cannot reach API at {args.base_url}. Start server first.\nError: {e}", file=sys.stderr)
        return 1
    candidates = data.get("candidates", [])
    total = data.get("total", 0)
    print(f"Loaded {len(candidates)} candidates (total {total})")

    if not candidates:
        print("No candidates to process.")
        return 0

    label = "" if args.no_label else args.label
    save_cvs_to = args.save_cvs_to.strip() or None
    cv_report: dict[str, dict] = {}
    if args.stage in ("cv_only", "all"):
        cv_report = await run_cv_pipeline(
            args.base_url, candidates, label, args.dry_run, save_cvs_to=save_cvs_to
        )
        for email, r in list(cv_report.items())[:10]:
            print(f"  CV: {email} -> source={r['cv_source']} stored={r['cv_stored']}")
        if len(cv_report) > 10:
            print(f"  ... and {len(cv_report) - 10} more")

    # Reload candidates so we have cv_parsed for Stage 2
    if args.stage in ("stage2", "all") and not args.dry_run and cv_report:
        try:
            data = _api_get(args.base_url, f"/api/anu/candidates?limit={args.limit}&offset=0")
            candidates = data.get("candidates", [])
        except Exception:
            pass

    out_dir = Path(args.output_dir)
    if args.stage in ("stage1", "all") and not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        stage1_content = _load_stage1_template(args.role_focus, args.cta)
        (out_dir / "stage1_intro.md").write_text(stage1_content, encoding="utf-8")
        print(f"Wrote {out_dir / 'stage1_intro.md'}")

    if args.stage in ("stage2", "all"):
        # Warm company context for Stage 2 (who we are, what we do, location). See data/knowledge/recruitment_company_intro_warm.txt.
        _warm_intro_path = DATA_KNOWLEDGE / "recruitment_company_intro_warm.txt"
        if _warm_intro_path.exists():
            company_intro_short = _warm_intro_path.read_text(encoding="utf-8").strip()
        else:
            company_intro_short = (
                "Signer: Rushabh runs Machinecraft Technologies (founder). "
                "Company: Machinecraft designs and builds industrial thermoforming machines (PF1, PF2, IMG, etc.) at Umargam; we support customers through design, build, FAT, installation, and service. "
                "Production flow: BOM and procurement → fabrication → fitting → assembly → testing (FAT) → dispatch; we coordinate across CAD, Production, Procurement, and Sales. "
                "Role: We are recruiting for the role stated below at Umargam — describe in 1–2 sentences what that role involves. "
                "Mandatory: Include the question: This role is based in Umargam. Are you willing to relocate to Umargam (or able to commute)? Please confirm briefly."
            )
        location_question = (
            "\n\n(Mandatory — include in email) This role is based in Umargam. Are you willing to relocate to Umargam (or able to commute)? Please confirm briefly."
        )
        for c in candidates:
            email = (c.get("email") or "").strip().lower()
            name = (c.get("name") or "").strip() or "Candidate"
            profile = c.get("profile") or {}
            cv_parsed = c.get("cv_parsed")
            role_str = profile.get("current_role") or ""
            role_key = _normalize_role(role_str)
            case_study_path = _case_study_path(role_key)
            case_study_text = case_study_path.read_text(encoding="utf-8") if case_study_path.exists() else "(No case study.)"
            dice_questions = _load_dice_questions(role_key) + location_question
            skills_questions = (
                _skills_questions_from_cv(cv_parsed) if cv_parsed
                else _skills_questions_from_cv(profile) if profile.get("skills")
                else "Tell us briefly about your relevant experience for this role."
            )
            if args.dry_run:
                print(f"  [dry-run] Stage 2 for {email} role={role_key}")
                continue
            job_context = _job_description_or_context(role_key)
            result = _draft_stage2(
                args.base_url,
                name,
                role_str or role_key,
                case_study_text,
                dice_questions,
                skills_questions,
                company_intro_short,
                job_description_or_context=job_context,
            )
            if not result:
                print(f"  Skip Stage 2 draft for {email} (API failed)", file=sys.stderr)
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_email = email.replace("@", "_at_").replace(".", "_")
            body = f"To: {email}\nSubject: {result.get('subject', 'Re: Your application')}\n\n{result.get('body', '')}"
            (out_dir / f"stage2_{safe_email}.md").write_text(body, encoding="utf-8")
            print(f"  Wrote stage2_{safe_email}.md")

    # Summary table
    print("\n--- Summary ---")
    print(f"{'Email':<40} {'Name':<25} {'CV source':<12} {'CV stored':<10} {'Stage2 file'}")
    print("-" * 100)
    for c in candidates:
        email = (c.get("email") or "")[:38]
        name = ((c.get("name") or "")[:23])
        r = cv_report.get((c.get("email") or "").strip().lower(), {})
        src = r.get("cv_source", "—")
        stored = "yes" if r.get("cv_stored") else "no"
        stage2_file = f"stage2_{email.replace('@', '_at_').replace('.', '_')}.md" if args.stage in ("stage2", "all") and not args.dry_run else "—"
        print(f"{email:<40} {name:<25} {src:<12} {stored:<10} {stage2_file}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
