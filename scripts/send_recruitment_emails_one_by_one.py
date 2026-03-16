#!/usr/bin/env python3
"""Draft a unique, tailored Stage 2 email per candidate and send one by one.

Each email is generated fresh via the API (LLM) so it's personalized (name, role, skills).
Usage:
  poetry run python scripts/send_recruitment_emails_one_by_one.py --limit 5
  poetry run python scripts/send_recruitment_emails_one_by_one.py --dry-run  # draft only, no send
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_KNOWLEDGE = PROJECT_ROOT / "data" / "knowledge"
OUT_DIR = PROJECT_ROOT / "data" / "recruitment_drafts"

# Already sent (do not send again)
SKIP_EMAILS = {
    "pratikkelawala000@gmail.com",
    "design.suraj91@gmail.com",
    "kangane.aakash@gmail.com",
    "jignesht1866@gmail.com",
    "panchalnaveen108@gmail.com",
    "nainitprajapati@gmail.com",
    "manishfarlya09@gmail.com",
    "prajapatitejesh@gmail.com",
    "pratikpro9@gmail.com",
    "yadnesh0077@gmail.com",
    "umesh.chunarkar116@gmail.com",
}

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
    if not (role_str or "").strip():
        return "default"
    r = role_str.strip().lower()
    first = r.split(",")[0].strip().lower()
    for k, v in ROLE_TO_KEY.items():
        if k in first or k in r:
            return v
    return "default"


# Friendly labels for open positions (used when we infer role from profile)
ROLE_KEY_TO_LABEL = {
    "cad": "CAD / Tool Design Engineer",
    "plc": "PLC / Electrical",
    "procurement": "Procurement",
    "cam": "CAM Programmer",
    "production_planning": "Production Planning",
    "plant_manager": "Plant Manager",
    "default": "the role you applied for",
}


def _infer_role_from_profile(profile: dict) -> str:
    """Infer role_key from profile skills/summary when current_role is missing or default.
    Returns one of: cad, plc, procurement, cam, production_planning, plant_manager, default.
    """
    text_parts = []
    skills = profile.get("skills") or []
    for s in skills:
        if isinstance(s, str) and s.strip():
            text_parts.append(s.strip().lower())
    summary = (profile.get("summary") or "")[:2000]
    if summary:
        text_parts.append(summary.lower())
    for h in profile.get("experience_highlights") or []:
        if isinstance(h, str):
            text_parts.append(h[:500].lower())
    combined = " ".join(text_parts)

    # Order matters: more specific first (e.g. CAM before CAD for "CNC programming")
    if any(
        x in combined
        for x in ("plc", "hmi", "scada", "electrical control", "control system", "ladder", "siemens", "allen bradley")
    ):
        return "plc"
    if any(x in combined for x in ("procurement", "vendor", "purchase order", "sap", "sourcing", "supply chain")):
        return "procurement"
    if any(x in combined for x in ("cam ", "cnc programming", "cnc ", "machining program", "mastercam", "fusion 360 cam")):
        return "cam"
    if any(
        x in combined
        for x in (
            "production planning",
            "scheduling",
            "shop floor",
            "plant manager",
            "production manager",
            "factory head",
        )
    ):
        return "plant_manager"
    if any(
        x in combined
        for x in (
            "solidworks",
            "autocad",
            "creo",
            "nx ",
            "catia",
            "drawing",
            "bom",
            "bill of material",
            "design engineer",
            "tool design",
            "mechanical design",
        )
    ):
        return "cad"
    return "default"


def _case_study_path(role_key: str) -> Path:
    if role_key in ("plant_manager", "production_planning"):
        return DATA_KNOWLEDGE / "plant_manager_case_study_22014_ALP_Delhi.md"
    return DATA_KNOWLEDGE / "recruitment_case_study_generic.md"


def _load_dice_questions(role_key: str) -> str:
    path = DATA_KNOWLEDGE / "recruitment_dice_questions.md"
    if not path.exists():
        return "1. Describe a time when you had to give difficult feedback.\n2. How do you prioritise when stakeholders pull in different directions?"
    text = path.read_text(encoding="utf-8")
    section_by_role = {
        "default": "Default set",
        "plant_manager": "Plant Manager",
        "production_planning": "Plant Manager",
        "cad": "CAD",
        "plc": "PLC",
        "procurement": "Procurement",
        "cam": "CAM",
    }
    section = section_by_role.get(role_key, "Default set")
    start = text.find("## " + section)
    if start < 0:
        start = text.find("## Default set")
    end = text.find("\n## ", start + 5) if start >= 0 else -1
    block = text[start:end].strip() if end > start else text
    lines = []
    for line in block.split("\n"):
        line = line.strip()
        if line and re.match(r"^\d+\.", line):
            lines.append(line)
            if len(lines) >= 4:
                break
    return "\n".join(lines) if lines else "1. Describe a time when you had to give difficult feedback."


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


def _skills_questions_from_profile(profile: dict) -> str:
    skills = profile.get("skills") or []
    tools = [s for s in skills if s and len(str(s).strip()) > 2][:4]
    if not tools:
        return "Tell us briefly about your relevant experience for this role."
    if len(tools) >= 2:
        return f"You mentioned experience with {', '.join(tools[:2])}. Can you describe a recent project where you used these (or similar) and how you applied them?"
    return f"You mentioned experience with {tools[0]}. Can you describe a recent project where you used it?"


def _api_get(base_url: str, path: str, timeout: int = 30) -> dict:
    import urllib.request
    req = urllib.request.Request(base_url.rstrip("/") + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _api_post(base_url: str, path: str, data: dict, timeout: int = 120) -> dict:
    import urllib.request
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft tailored Stage 2 per candidate and send one by one")
    parser.add_argument("--base-url", default=os.environ.get("IRA_API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--limit", type=int, default=999, help="Max candidates to process (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Draft only, do not send")
    parser.add_argument("--skip", type=str, default="", help="Comma-separated emails to skip (e.g. a@b.com,c@d.com)")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    skip = set(SKIP_EMAILS)
    if args.skip:
        skip.update(e.strip().lower() for e in args.skip.split(",") if "@" in e)

    try:
        data = _api_get(base_url, "/api/anu/candidates?limit=500&offset=0")
    except Exception as e:
        print(f"Cannot fetch candidates: {e}", file=sys.stderr)
        return 1
    candidates = data.get("candidates", [])[: args.limit]
    company_path = DATA_KNOWLEDGE / "recruitment_company_intro_warm.txt"
    company_intro = company_path.read_text(encoding="utf-8").strip() if company_path.exists() else "Machinecraft Technologies (Umargam) is recruiting."
    location_line = "\n\n(Mandatory — include in email) This role is based in Umargam. Are you willing to relocate to Umargam (or able to commute)? Please confirm briefly."

    sent = 0
    failed = 0
    for c in candidates:
        email = (c.get("email") or "").strip().lower()
        if not email or "@" not in email or email in skip:
            continue
        name = (c.get("name") or "").strip() or "Candidate"
        profile = c.get("profile") or {}
        role_str = profile.get("current_role") or ""
        role_key = _normalize_role(role_str)
        if role_key == "default":
            role_key = _infer_role_from_profile(profile)
            if role_key != "default":
                role_str = ROLE_KEY_TO_LABEL.get(role_key, role_str or "the role you applied for")
            else:
                role_str = role_str or "CAD"
        else:
            role_str = role_str or ROLE_KEY_TO_LABEL.get(role_key, "the role you applied for")
        case_path = _case_study_path(role_key)
        case_study = case_path.read_text(encoding="utf-8") if case_path.exists() else "(No case study.)"
        dice_questions = _load_dice_questions(role_key) + location_line
        skills_q = _skills_questions_from_profile(profile)

        job_context = _job_description_or_context(role_key)
        payload = {
            "candidate_name": name.split()[0] if name else "Candidate",
            "role": role_str,
            "case_study_text": case_study,
            "dice_questions": dice_questions,
            "skills_questions": skills_q,
            "company_intro_short": company_intro,
            "job_description_or_context": job_context,
        }
        try:
            draft = _api_post(base_url, "/api/anu/draft-recruitment-stage2", payload, timeout=120)
        except Exception as e:
            print(f"  [FAIL] {email} draft: {e}", file=sys.stderr)
            failed += 1
            continue
        subject = draft.get("subject", "Next Steps: Machinecraft Technologies")
        body = draft.get("body", "")
        Out_dir = Path(OUT_DIR)
        Out_dir.mkdir(parents=True, exist_ok=True)
        safe = email.replace("@", "_at_").replace(".", "_")
        (Out_dir / f"stage2_{safe}.md").write_text(f"To: {email}\nSubject: {subject}\n\n{body}", encoding="utf-8")

        if args.dry_run:
            print(f"  [dry-run] {email} -> drafted (not sent)")
            sent += 1
            continue
        try:
            send_payload = {"to": email, "subject": subject, "body": body}
            _api_post(base_url, "/api/email/send", send_payload, timeout=30)
            print(f"  [SENT] {email} ({name})")
            sent += 1
        except Exception as e:
            print(f"  [FAIL] {email} send: {e}", file=sys.stderr)
            failed += 1
        time.sleep(1.5)

    print(f"\nDone. Sent: {sent}, Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
