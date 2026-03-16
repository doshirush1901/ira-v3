#!/usr/bin/env python3
"""Redraft Stage 2 email for one candidate via API. Run after server is up.

Usage:
  poetry run python scripts/redraft_one_candidate.py abhishek965115@gmail.com
  poetry run python scripts/redraft_one_candidate.py abduldalal18@gmail.com --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_KNOWLEDGE = PROJECT_ROOT / "data" / "knowledge"
OUT_DIR = PROJECT_ROOT / "data" / "recruitment_drafts"


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
    parser = argparse.ArgumentParser(description="Redraft Stage 2 for one candidate via API")
    parser.add_argument("email", help="Candidate email (e.g. abhishek965115@gmail.com)")
    parser.add_argument("--base-url", default=os.environ.get("IRA_API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--output-dir", default=str(OUT_DIR), help="Directory to write stage2_<email>.md")
    args = parser.parse_args()
    email = args.email.strip().lower()
    if "@" not in email:
        print("Invalid email", file=sys.stderr)
        return 1

    base_url = args.base_url.rstrip("/")
    try:
        c = _api_get(base_url, f"/api/anu/candidates/by-email?email={email}")
    except Exception as e:
        print(f"Cannot fetch candidate: {e}", file=sys.stderr)
        return 1

    name = (c.get("name") or "").strip() or "Candidate"
    profile = c.get("profile") or {}
    role_str = profile.get("current_role") or "CAD"
    skills = profile.get("skills") or []
    tools = [s for s in skills if s and len(str(s).strip()) > 2][:4]
    if len(tools) >= 2:
        skills_q = f"You mentioned experience with {', '.join(tools[:2])}. Can you describe a recent project where you used these (or similar) and how you applied them?"
    elif tools:
        skills_q = f"You mentioned experience with {tools[0]}. Can you describe a recent project where you used it?"
    else:
        skills_q = "Tell us briefly about your relevant experience for this role."

    # Role key for job context (CAD gets recruitment_cad_jd.md)
    role_key = "cad" if (role_str or "").strip().lower().startswith(("cad", "design")) else "default"
    def _job_context(rk: str) -> str:
        parts = []
        open_path = DATA_KNOWLEDGE / "recruitment_open_positions.md"
        if open_path.exists():
            parts.append(open_path.read_text(encoding="utf-8").strip())
        if rk == "cad":
            cad_path = DATA_KNOWLEDGE / "recruitment_cad_jd.md"
            if cad_path.exists():
                parts.append(cad_path.read_text(encoding="utf-8").strip())
        return "\n\n---\n\n".join(parts) if parts else ""

    company_path = DATA_KNOWLEDGE / "recruitment_company_intro_warm.txt"
    company_intro = company_path.read_text(encoding="utf-8").strip() if company_path.exists() else "Machinecraft Technologies (Umargam) is recruiting."
    job_description_or_context = _job_context(role_key)
    case_path = DATA_KNOWLEDGE / "recruitment_case_study_generic.md"
    case_study = case_path.read_text(encoding="utf-8") if case_path.exists() else "(No case study.)"
    dice_path = DATA_KNOWLEDGE / "recruitment_dice_questions.md"
    dice_text = dice_path.read_text(encoding="utf-8") if dice_path.exists() else ""
    if "## CAD" in dice_text:
        start = dice_text.find("## CAD")
        end = dice_text.find("##", start + 5) if start >= 0 else -1
        dice_section = dice_text[start:end].strip() if end > start else dice_text
        dice_lines = [l.strip() for l in dice_section.split("\n") if l.strip() and (l.strip().startswith("1.") or l.strip().startswith("2.") or l.strip().startswith("3.") or l.strip().startswith("4."))][:4]
        dice_questions = "\n".join(dice_lines) if dice_lines else "1. Describe a time when you had to give difficult feedback. 2. How do you prioritise when stakeholders pull in different directions?"
    else:
        dice_questions = "1. Describe a time when you had to give difficult feedback. 2. How do you prioritise when stakeholders pull in different directions?"
    dice_questions += "\n\n(Mandatory — include in email) This role is based in Umargam. Are you willing to relocate to Umargam (or able to commute)? Please confirm briefly."

    payload = {
        "candidate_name": name.split()[0] if name else "Candidate",
        "role": role_str,
        "case_study_text": case_study,
        "dice_questions": dice_questions,
        "skills_questions": skills_q,
        "company_intro_short": company_intro,
        "job_description_or_context": job_description_or_context,
    }
    try:
        result = _api_post(base_url, "/api/anu/draft-recruitment-stage2", payload, timeout=120)
    except Exception as e:
        print(f"Draft API failed: {e}", file=sys.stderr)
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_email = email.replace("@", "_at_").replace(".", "_")
    body = f"To: {email}\nSubject: {result.get('subject', 'Re: Your application')}\n\n{result.get('body', '')}"
    (out_dir / f"stage2_{safe_email}.md").write_text(body, encoding="utf-8")
    print(f"Wrote {out_dir / f'stage2_{safe_email}.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
