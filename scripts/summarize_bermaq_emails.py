#!/usr/bin/env python3
"""
Pull all emails from a contact (e.g. mcanudas@bermaq.com) and write a summary.

Use case: Contact was interested in being an agent; has sent customer inquiries
and received proposals. This script fetches all threads and produces:
  - Overview (total threads, date range)
  - Per-thread: subject, dates, message count, direction (inbound/outbound), snippet
  - Full thread content for reference

Usage:
    python scripts/summarize_bermaq_emails.py
    python scripts/summarize_bermaq_emails.py --email other@domain.com --output data/other_summary.md
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load env for any Gmail/OpenAI config
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

CONTACT_EMAIL = "mcanudas@bermaq.com"
OUTPUT_DIR = PROJECT_ROOT / "data" / "summaries"
OUTPUT_FILE = OUTPUT_DIR / "bermaq_mcanudas_email_summary.md"


def main():
    parser = argparse.ArgumentParser(description="Summarize all emails with a contact")
    parser.add_argument("--email", default=CONTACT_EMAIL, help="Contact email (from/to)")
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="Output markdown file path")
    parser.add_argument("--max-threads", type=int, default=100, help="Max threads to fetch (default 100)")
    args = parser.parse_args()

    contact_email = args.email.strip().lower()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Import only google_tools to avoid loading the full tools package
    import importlib.util
    gt_path = PROJECT_ROOT / "openclaw" / "agents" / "ira" / "src" / "tools" / "google_tools.py"
    spec = importlib.util.spec_from_file_location("google_tools", gt_path)
    google_tools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(google_tools)
    gmail_list_messages = google_tools.gmail_list_messages
    gmail_get_thread = google_tools.gmail_get_thread

    query = f"from:{contact_email} OR to:{contact_email}"
    print(f"Searching Gmail: {query}")
    rows = gmail_list_messages(query, max_results=500)
    if not rows:
        print("No messages found.")
        output_path.write_text(
            f"# Email summary: {contact_email}\n\nNo messages found for query: `{query}`.\n",
            encoding="utf-8",
        )
        return

    # Unique thread IDs preserving order (newest first from Gmail)
    seen = set()
    thread_ids = []
    for r in rows:
        tid = r.get("thread_id") or ""
        if tid and tid not in seen:
            seen.add(tid)
            thread_ids.append(tid)
    thread_ids = thread_ids[: args.max_threads]

    print(f"Found {len(rows)} messages in {len(thread_ids)} threads. Fetching thread content...")

    threads_data = []
    for i, thread_id in enumerate(thread_ids):
        try:
            content = gmail_get_thread(thread_id, max_messages=50)
            threads_data.append((thread_id, content))
        except Exception as e:
            print(f"  Thread {thread_id}: {e}")
            threads_data.append((thread_id, f"(Error: {e})"))

    # Build summary
    lines = [
        f"# Email summary: {contact_email}",
        "",
        f"**Context:** Contact was interested in being an agent; has sent customer inquiries and received proposals from Machinecraft.",
        "",
        f"**Query:** `{query}`",
        f"**Total messages:** {len(rows)}",
        f"**Threads:** {len(thread_ids)}",
        "",
        "---",
        "",
        "## Threads (newest first)",
        "",
    ]

    for thread_id, content in threads_data:
        if content.startswith("(Gmail ") or content.startswith("(Error") or content.startswith("(Thread"):
            lines.append(f"### Thread `{thread_id}`")
            lines.append(content)
            lines.append("")
            continue
        first_line = content.split("\n")[0] if content else ""
        subject = first_line.replace("Thread: ", "").split(" (")[0] if "Thread:" in first_line else thread_id
        lines.append(f"### {subject}")
        lines.append(f"- Thread ID: `{thread_id}`")
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>Full thread</summary>")
        lines.append("")
        lines.append("```")
        lines.append(content)
        lines.append("```")
        lines.append("</details>")
        lines.append("")

    body = "\n".join(lines)
    output_path.write_text(body, encoding="utf-8")
    print(f"Summary written to: {output_path}")
    print(f"  Threads: {len(thread_ids)}  Messages: {len(rows)}")


if __name__ == "__main__":
    main()
