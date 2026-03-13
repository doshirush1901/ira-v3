#!/usr/bin/env python3
"""Download PDF attachments from Gmail threads for a contact, then run PDF analysis and memory update.

1. Searches Gmail for messages to/from the contact.
2. Downloads all PDF attachments into data/imports/downloaded_from_emails/<folder>/.
3. Optionally runs PDF text extraction + LLM to extract quote data (e.g. ATF price, PF1 price).
4. Updates the TO_SEND file with extracted prices and stores a master memory for the contact.

Requires: GOOGLE_* env (credentials_path, token_path) and Gmail API token with read scope.
Alexandros will index data/imports/downloaded_from_emails/ automatically (it's under data/imports/).

Usage:
  poetry run python scripts/download_email_attachments.py --email pinto@forma3d.pt --folder forma3d_eduardo
  poetry run python scripts/download_email_attachments.py --email pinto@forma3d.pt --folder forma3d_eduardo --analyze --memory --to-send data/imports/24_WebSite_Leads/email_lead3_eduardo_pinto_TO_SEND.md
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

DOWNLOAD_BASE = PROJECT_ROOT / "data" / "imports" / "downloaded_from_emails"


def _build_gmail_service():
    """Build Gmail API service using project credentials (same as EmailProcessor)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    from ira.config import get_settings

    # Use same scope as email processor training mode; when loading existing token
    # use None so the token's own scopes are used on refresh (avoids invalid_scope
    # if token was created with operational/send scopes).
    read_scope = ["https://www.googleapis.com/auth/gmail.readonly"]
    cfg = get_settings().google
    creds_path = Path(cfg.credentials_path)
    token_path = Path(cfg.token_path)
    if not creds_path.is_absolute():
        creds_path = PROJECT_ROOT / creds_path
    if not token_path.is_absolute():
        token_path = PROJECT_ROOT / token_path

    creds = None
    if token_path.exists():
        try:
            # Load with token's existing scopes so refresh doesn't request a different scope
            creds = Credentials.from_authorized_user_file(str(token_path), None)
        except Exception:
            creds = Credentials.from_authorized_user_file(str(token_path), read_scope)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            # Token may have been created with different scopes; re-auth with read scope
            if "invalid_scope" in str(e).lower() or "Bad Request" in str(e):
                print("Token scope mismatch; re-authorizing with Gmail read access...", file=sys.stderr)
                creds = None
            else:
                raise
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), read_scope)
        creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _collect_attachment_parts(payload: dict, acc: list[tuple[str, dict]]) -> None:
    """Recursively collect (filename, part) for parts that have a filename and body (data or attachmentId)."""
    for part in payload.get("parts", []):
        filename = (part.get("filename") or "").strip()
        body = part.get("body") or {}
        if filename and (body.get("attachmentId") or body.get("data")):
            acc.append((filename, part))
        _collect_attachment_parts(part, acc)


def _download_attachment(service, user_id: str, message_id: str, part: dict) -> bytes:
    """Download attachment data for a part (uses attachmentId if present, else body.data)."""
    body = part.get("body") or {}
    if body.get("data"):
        return base64.urlsafe_b64decode(body["data"])
    att_id = body.get("attachmentId")
    if not att_id:
        return b""
    att = (
        service.users()
        .messages()
        .attachments()
        .get(userId=user_id, messageId=message_id, id=att_id)
        .execute()
    )
    return base64.urlsafe_b64decode(att.get("data", ""))


def download_pdfs(contact_email: str, folder_name: str, max_messages: int = 80) -> list[Path]:
    """Search Gmail for messages to/from contact, download PDF attachments into DOWNLOAD_BASE/folder_name/. Returns list of saved paths."""
    service = _build_gmail_service()
    # Search both directions
    q_to = f"to:{contact_email}"
    q_from = f"from:{contact_email}"
    all_msg_ids: set[str] = set()
    for q in [q_to, q_from]:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=q, maxResults=max_messages)
            .execute()
        )
        for m in resp.get("messages", []):
            all_msg_ids.add(m["id"])

    out_dir = DOWNLOAD_BASE / folder_name
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    seen_names: set[str] = set()

    for msg_id in all_msg_ids:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )
        payload = msg.get("payload") or {}
        parts: list[tuple[str, dict]] = []
        _collect_attachment_parts(payload, parts)
        for filename, part in parts:
            if not filename.lower().endswith(".pdf"):
                continue
            # Dedupe by filename (keep first)
            base_name = re.sub(r"[^\w\-\.]", "_", filename)
            if base_name in seen_names:
                base_name = f"{msg_id}_{base_name}"
            seen_names.add(base_name)
            out_path = out_dir / base_name
            if out_path.exists():
                saved.append(out_path)
                continue
            try:
                data = _download_attachment(service, "me", msg_id, part)
                if data:
                    out_path.write_bytes(data)
                    saved.append(out_path)
                    print(f"  Saved: {out_path.relative_to(PROJECT_ROOT)}")
            except Exception as e:
                print(f"  Skip {filename}: {e}", file=sys.stderr)
    return saved


async def analyze_pdfs_and_extract_prices(pdf_paths: list[Path], contact_name: str) -> dict:
    """Extract text from PDFs and use LLM to get all machines with specs and prices."""
    from ira.brain.document_ingestor import read_pdf
    from ira.services.llm_client import get_llm_client

    if not pdf_paths:
        return {}
    texts = []
    for p in pdf_paths:
        try:
            t = read_pdf(p)
            if t and len(t.strip()) > 100:
                texts.append(f"[File: {p.name}]\n{t[:12000]}")
        except Exception:
            continue
    if not texts:
        return {}
    combined = "\n\n---\n\n".join(texts)[:40000]
    system = """You are extracting quote/proposal data from PDFs (Machinecraft thermoforming machines).
You must look at EVERY PDF and list EVERY machine offer found across all of them.

Output a JSON object with this structure:
- machines: array of objects, one per machine quoted. Each object has:
  - model: string (e.g. "PF1-X-1210", "ATF1212", "FCS-6070-3S", "Custom-size ATF", "AM roll-fed")
  - price: string (e.g. "EUR 120,000", "€95,000", "110,000 EUR") — always include if present in the PDF
  - specs_short: string, one line of key specs (forming area, roll-fed/sheet-fed, cycle, depth) or empty string if not found

Optional keys: currency, quote_date, valid_until, atf_price, pf1_price.

Rules: Extract from ALL PDFs. Include ATF, PF1, FCS, AM, and any other model names. Never return an empty machines array if any PDF clearly mentions a machine and price. Output only valid JSON, no markdown. No trailing commas after the last array element."""
    user = f"Contact: {contact_name}. Extract all machines, prices, and key specs from these PDFs:\n\n{combined}"
    client = get_llm_client()
    raw = await client.generate_text(
        system=system,
        user=user,
        max_tokens=1200,
        temperature=0.1,
        name="download_email_attachments_extract",
    )
    import json
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw).rstrip("`")
    # Strip trailing commas before ] or } so LLM output parses
    raw_clean = re.sub(r",\s*([}\]])", r"\1", raw)
    try:
        data = json.loads(raw_clean)
        # Normalize: ensure machines list exists; backfill atf_price/pf1_price from first matching machine
        if "machines" not in data or not isinstance(data["machines"], list):
            data["machines"] = []
        for m in data["machines"]:
            if not isinstance(m, dict):
                continue
            model = (m.get("model") or "").upper()
            price = m.get("price") or ""
            if "ATF" in model and not data.get("atf_price"):
                data["atf_price"] = price
            if "PF1" in model and not data.get("pf1_price"):
                data["pf1_price"] = price
        return data
    except json.JSONDecodeError:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("machines"):
                return data
        except Exception:
            pass
        return {"raw": raw, "machines": []}


def _build_quote_block(extracted: dict) -> str:
    """Build email-ready bullet block from extracted machines (for INSERT_LATEST_QUOTE)."""
    machines = extracted.get("machines") or []
    if not machines:
        atf = extracted.get("atf_price")
        pf1 = extracted.get("pf1_price")
        if atf or pf1:
            lines = []
            if atf:
                lines.append(f"• Custom-size ATF (roll-fed): {atf}")
            if pf1:
                lines.append(f"• PF1: {pf1}")
            if lines:
                return "\n".join(lines)
        return "• (Quote details could not be extracted from PDFs — please refer to the quote we sent you.)"
    lines = []
    for m in machines:
        if not isinstance(m, dict):
            continue
        model = m.get("model") or "Machine"
        price = m.get("price") or ""
        specs = (m.get("specs_short") or "").strip()
        if price:
            line = f"• **{model}:** {price}"
            if specs:
                line += f" — {specs}"
            lines.append(line)
        else:
            lines.append(f"• **{model}** — {specs}" if specs else f"• **{model}**")
    return "\n".join(lines) if lines else "• (No machines extracted.)"


def _normalize_extracted(extracted: dict) -> dict:
    """If extraction left machines empty but raw JSON exists, parse it (with trailing-comma fix)."""
    if not extracted:
        return extracted
    if (extracted.get("machines") or []) and isinstance(extracted.get("machines"), list):
        return extracted
    raw = extracted.get("raw") or ""
    if not raw or not isinstance(raw, str):
        return extracted
    raw_clean = re.sub(r",\s*([}\]])", r"\1", raw)
    try:
        data = json.loads(raw_clean)
        if isinstance(data, dict) and isinstance(data.get("machines"), list):
            for m in data.get("machines") or []:
                if not isinstance(m, dict):
                    continue
                model = (m.get("model") or "").upper()
                price = m.get("price") or ""
                if "ATF" in model and not data.get("atf_price"):
                    data["atf_price"] = price
                if "PF1" in model and not data.get("pf1_price"):
                    data["pf1_price"] = price
            return data
    except json.JSONDecodeError:
        pass
    return extracted


def update_to_send_with_quote(to_send_path: Path, extracted: dict) -> None:
    """Insert extracted machines/specs/prices into TO_SEND: replace <!-- INSERT_LATEST_QUOTE --> with the quote block."""
    if not extracted or not to_send_path.exists():
        return
    extracted = _normalize_extracted(extracted)
    block = _build_quote_block(extracted)
    text = to_send_path.read_text(encoding="utf-8")
    placeholder = "<!-- INSERT_LATEST_QUOTE -->"
    if placeholder not in text:
        # Fallback: replace legacy placeholders so old templates still work
        atf = extracted.get("atf_price")
        pf1 = extracted.get("pf1_price")
        if atf and "[ATF price]" in text:
            text = text.replace("[ATF price]", str(atf))
        if pf1 and "[PF1 price]" in text:
            text = text.replace("[PF1 price]", str(pf1))
        to_send_path.write_text(text, encoding="utf-8")
        print(f"Updated {to_send_path.name} with ATF={atf}, PF1={pf1} (legacy placeholders)")
        return
    text = text.replace(placeholder, block)
    to_send_path.write_text(text, encoding="utf-8")
    print(f"Updated {to_send_path.name} with quote block ({len(extracted.get('machines') or [])} machines)")


def store_memory_update(contact_email: str, contact_name: str, extracted: dict, folder_name: str) -> None:
    """Store a master memory that latest quote has these prices; PDFs are in downloaded_from_emails/folder_name."""
    try:
        import httpx
    except ImportError:
        return
    mem_text = (
        f"Contact {contact_email}: latest quote we sent included "
        f"custom-size ATF at {extracted.get('atf_price') or 'see quote'}, "
        f"PF1 at {extracted.get('pf1_price') or 'see quote'}. "
        f"PDFs from that quote are stored in data/imports/downloaded_from_emails/{folder_name}/; Alexandros can search them."
    )
    try:
        r = httpx.post(
            "http://localhost:8000/api/memory/store",
            json={"content": mem_text, "user_id": contact_email},
            timeout=10.0,
        )
        if r.status_code == 200:
            print("Stored memory update for", contact_email)
        else:
            print("Memory store returned", r.status_code, r.text[:200], file=sys.stderr)
    except Exception as e:
        print("Memory store failed (is Ira API running?):", e, file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PDF attachments from Gmail for a contact")
    parser.add_argument("--email", required=True, help="Contact email (to/from)")
    parser.add_argument("--folder", required=True, help="Subfolder name under downloaded_from_emails/ (e.g. forma3d_eduardo)")
    parser.add_argument("--max-messages", type=int, default=80, help="Max messages to scan")
    parser.add_argument("--analyze", action="store_true", help="Run PDF analysis and LLM extraction")
    parser.add_argument("--memory", action="store_true", help="Store master memory update (requires Ira API)")
    parser.add_argument("--to-send", type=Path, help="Path to TO_SEND.md; replaces <!-- INSERT_LATEST_QUOTE --> with extracted machines/specs/prices")
    parser.add_argument("--name", default="", help="Contact name for LLM context")
    args = parser.parse_args()
    if args.to_send and not args.to_send.is_absolute():
        args.to_send = PROJECT_ROOT / args.to_send

    print(f"Downloading PDFs from threads with {args.email} into downloaded_from_emails/{args.folder}/ ...")
    paths = download_pdfs(args.email, args.folder, max_messages=args.max_messages)
    print(f"Downloaded {len(paths)} PDF(s).")

    if args.analyze and paths:
        name = args.name or args.email.split("@")[0]
        extracted = asyncio.run(analyze_pdfs_and_extract_prices(paths, name))
        if extracted:
            print("Extracted:", extracted)
        if args.to_send and extracted:
            update_to_send_with_quote(args.to_send, extracted)
        if extracted:
            summary_path = DOWNLOAD_BASE / args.folder / "quote_summary.md"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            lines = ["# Quote data extracted from PDFs", ""]
            for k, v in extracted.items():
                if k != "raw" and v is not None:
                    lines.append(f"- **{k}**: {v}")
            if len(lines) > 2:
                summary_path.write_text("\n".join(lines), encoding="utf-8")
                print(f"Wrote {summary_path.relative_to(PROJECT_ROOT)}")
        if args.memory and extracted:
            store_memory_update(args.email, name, extracted, args.folder)
    elif args.memory and not args.analyze:
        print("Use --analyze with --memory to store extracted quote data.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
