# Plain-text email: sources & best practices (text only, no HTML)

Curated sources for drafting **beautiful, scannable plain-text emails**. All recommendations are text-based only (no HTML). Use these to refine prompts and human review.

---

## Best-practice summaries (from external sources)

### 1. Litmus — Why plain text still works & how to make it scannable

**Source:** [Litmus – Best practices for plain text emails](https://litmus.com/blog/best-practices-for-plain-text-emails-a-look-at-why-theyre-important)

- **Headers:** Use ALL CAPS or symbols (e.g. `**Header**` with dashes underneath, or `#` / `##` Markdown-style) to separate sections. Create a clear skimming path.
- **Line breaks:** Do **not** insert hard line breaks every 60 characters (old habit); modern clients wrap. Use line breaks only for **whitespace between sections** and paragraphs.
- **Whitespace:** Single blank line between paragraphs; more space between major sections. Makes CTAs easy to tap on mobile.
- **Lists:** Use `-`, `*`, or `+` for bullets (no HTML). Keeps hierarchy without design.
- **CTAs:** One or two clear CTAs; stand out with line breaks and clear wording. Avoid a wall of links.
- **Links:** Minimal. Only essential links; label them clearly (e.g. "Read more >>> https://...").

### 2. Outbound Rocks — 7 best practices for plain text email

**Source:** [Outbound Rocks – 7 best practices](https://outboundrocks.com/en/7-best-practices-to-follow-when-crafting-a-plain-text-email/)

- **Personalize:** Name, situation-specific details. Shows you’ve done the work.
- **Format:** Concise; break up for scanning. All-caps section headers or asterisks for key points. Don’t overdo symbols.
- **Clear CTAs:** Strong verbs, explicit next step (e.g. "Click here to download the report" not "Learn more").
- **Less is more:** Few links, line breaks for white space, short bullet lists with hyphens, no clutter.
- **Tone:** Friendly, professional; templates as framework, not script. Avoid robotic language.

(They cite 21% higher click-to-open and 17% higher click-through for plain text vs HTML in some benchmarks.)

### 3. Line length & typography (RFC and netiquette)

**Sources:** [Dan's Mail Format – Line length](https://mailformat.dan.info/body/linelength.html), [Stack Overflow – wrap at 72 chars](https://stackoverflow.com/questions/4297574/do-i-need-to-wrap-email-messages-longer-than-72-characters-in-a-line)

- **78 characters:** RFC 5322 recommendation (legacy 80-column displays).
- **65–72 characters:** Conservative; leaves room for quote markers (`>`) in replies. Our prompts use ~60–72 for readability.
- **998 characters:** Hard max per line (RFC); longer can cause issues.

### 4. Plain text email template (structure example)

**Source:** [GitHub Gist – plain text email template](https://gist.github.com/rodriguezcommaj/b1cdf66e7152982e62e57211fe9abfc6)

- Greeting → short intro paragraph.
- Bullet list (`-` or `*`).
- **Section divider:** e.g. `_,.-'~'-.,__,.-'~'-.,__` or `---` to separate blocks.
- **Section title** in caps or with `#` / `##`.
- One CTA per section with `>>> https://...`.
- Footer: address, unsubscribe, disclaimer.

We use a cleaner variant: optional `———` or a short label (e.g. `WHERE WE LEFT OFF —`) instead of decorative ASCII, to keep a professional, MBB-style look.

---

## Open source / repos (text-focused)

| Resource | What it is | Use for |
|----------|------------|--------|
| [rodriguezcommaj plain text template (Gist)](https://gist.github.com/rodriguezcommaj/b1cdf66e7152982e62e57211fe9abfc6) | Example structure: sections, bullets, dividers, CTA | Structure and spacing ideas |
| [getclera/mail](https://github.com/getclera/mail) | OSS outreach email repo (engineering talent); variables, personalization | Pattern for personalization and structure |
| [PaulleDemon/Email-automation](https://github.com/PaulleDemon/Email-automation) | Cold email outreach; templates (Jinja2), follow-ups | Template + variable patterns (we stay text-only) |

**Note:** Many OSS “email template” repos are HTML (e.g. MJML). For **text only**, the Gist above and the Litmus/Outbound Rocks articles are the most directly applicable.

---

## How we use this in Ira

- **prompts/email_final_format_style.txt** — Structure (greeting → hook → recap → key data → CTA → sign-off), spacing, section labels, bullets, line length ~60–72, Rushabh voice. Aligned with the practices above.
- **data/knowledge/outgoing_marketing_email_workflow.md** — Section 5c “Making the email beautiful” points here and to this doc for plain-text standards.
- When improving drafts: prefer **one idea per paragraph**, **clear section breaks**, **one primary CTA**, **minimal links**, **no hard wraps mid-sentence** (break at clause/sentence end).

---

*Last updated from external sources: 2025. Re-check links if using in production.*
