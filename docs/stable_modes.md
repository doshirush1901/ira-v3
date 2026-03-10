# Ira stable modes

Stable modes are well-defined, tested flows that Ira supports and we keep working. When the user says **"add this to stable list"**, add the current topic or flow to this list.

## Current stable modes

1. **Email reply flow (Cursor)**  
   Read mail → draft reply → show draft in Cursor → user can say "change X" to redraft (repeat until satisfied) → user says "send" → call `POST /api/email/send` with current draft. No auto-send; send only on explicit "send". Documented in `.cursor/rules/ira-api.mdc` §4b.

---

*Add new entries when the user says "add this to stable list".*
