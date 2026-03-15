# Ira stable modes

Stable modes are well-defined, tested flows that Ira supports and we keep working. When the user says **"add this to stable list"**, add the current topic or flow to this list.

## Current stable modes

1. **Email reply flow (Cursor)**  
   Read mail → draft reply → show draft in Cursor → user can say "change X" to redraft (repeat until satisfied) → user says "send" → call `POST /api/email/send` with current draft. No auto-send; send only on explicit "send". Documented in `.cursor/rules/ira-api.mdc` §4b.

2. **Read latest + draft reply**  
   User says: "Read latest from [person], draft reply."  
   - **Explore:** `search_emails(from_address="...")` to find latest thread.  
   - **Think:** What should the reply cover? Check CRM/Neo4j for context.  
   - **Act:** Calliope drafts using `email_final_format_style.txt` + `email_rushabh_voice_brand.txt`.  
   - **Result:** Show draft (To, Subject, Body) in Cursor. Send only on explicit "send."

3. **Summarize thread**  
   User says: "Summarize thread X" or "What's the latest on [topic] with [person]?"  
   - **Explore:** `read_email_thread(thread_id)` or `search_emails` to find the thread.  
   - **Think:** Extract key points, decisions, action items.  
   - **Act:** Summarize into structured format (key points, decisions, next steps).  
   - **Result:** Show summary in Cursor with thread reference.

4. **Find all about project/person**  
   User says: "Find everything about Project Y" or "What do we know about [company]?"  
   - **Explore:** Qdrant (historical), Gmail (recent), Neo4j (contacts/relationships).  
   - **Think:** Compile across sources; note gaps.  
   - **Act:** Build a structured profile (contacts, quotes, emails, timeline).  
   - **Result:** Show compiled profile with sources. Note if any source was unavailable.

5. **Draft follow-up from template**  
   User says: "Follow up with [person] about [topic]."  
   - **Explore:** CRM for deal status, email history for last touchpoint.  
   - **Think:** Pick appropriate template (follow-up, re-engagement, NDA). Check `email_final_format_style.txt`.  
   - **Act:** Calliope fills template with CRM/email context using `email_rushabh_voice_brand.txt`.  
   - **Result:** Show draft in Cursor. Send only on explicit "send."

6. **Email-to-CRM**  
   User says: "Log this email thread to CRM" or "Update CRM from [thread]."  
   - **Explore:** `read_email_thread` to get full thread content.  
   - **Think:** Extract entities (contact, company, machine, deal stage, value).  
   - **Act:** Prometheus/Populator update CRM with extracted data.  
   - **Result:** Show what was added/updated in CRM. Confirm with user.

---

*Add new entries when the user says "add this to stable list".*
