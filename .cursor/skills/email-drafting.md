---
description: >
  Email drafting skill — composes professional emails using Ira's Calliope agent,
  with context from CRM and knowledge base. Use when the user asks to write,
  draft, or send an email.
---

# Email Drafting Skill

## When to Use
Use this skill when the user asks to draft, write, compose, or send an email.

## Execution Steps

1. **Gather context about the recipient**:
   Call `search_crm` with the recipient's name or email to understand the
   relationship, recent interactions, and deal status.

2. **Determine the email purpose and tone**:
   Based on the user's request and CRM context, identify:
   - Purpose: follow-up, proposal, introduction, support, etc.
   - Tone: formal (new contact), warm (existing relationship), urgent (deadline)

3. **Draft the email**:
   Call `draft_email` with the recipient, subject, and full context including
   CRM findings and the user's instructions.

4. **Present for review**:
   Show the draft to the user. Ask: "Shall I refine anything before saving?"

5. **Important**: Ira is in TRAINING mode. Emails are saved as drafts only.
   Always remind the user that emails will NOT be sent automatically.

## Output Format
Present the email clearly:
```
**To:** [recipient]
**Subject:** [subject line]

[Email body]

---
TRAINING MODE: This email has been saved as a draft. It will NOT be sent automatically.
```
