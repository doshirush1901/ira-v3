---
description: >
  Deep research skill — searches Ira's knowledge base, CRM, and external sources
  to compile comprehensive findings on a topic. Use when the user asks for
  research, analysis, or "find out about X".
---

# Research Skill

## When to Use
Use this skill when the user asks to research a topic, find information, or
compile data from multiple sources.

## Execution Steps

1. **Query the knowledge base first**:
   Call `search_knowledge` with the research topic to find internal documents.

2. **Check the CRM for relevant records**:
   Call `search_crm` if the topic involves a customer, deal, or contact.

3. **Delegate to specialist agents**:
   - Use `ask_agent("clio", ...)` for factual knowledge base queries.
   - Use `ask_agent("iris", ...)` for external web research and news.
   - Use `ask_agent("alexandros", ...)` for archived document lookup.

4. **Cross-reference findings**:
   Compare results from at least 2 sources. Flag any conflicts.

5. **Compile results**:
   Return findings as a structured summary with source citations.

## Output Format
```markdown
## Research: [Topic]

### Key Findings
1. [Finding with source citation]
2. [Finding with source citation]

### Sources Consulted
- [Source 1]: [What it said]
- [Source 2]: [What it said]

### Confidence Level
[HIGH / MEDIUM / LOW] — based on source agreement and recency
```
