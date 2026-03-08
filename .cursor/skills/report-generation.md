---
description: >
  Report generation skill — uses the agent loop to compile multi-agent findings
  into a structured document (Markdown or PDF). Use when the user asks for a
  report, summary, analysis document, or business review.
---

# Report Generation Skill

## When to Use
Use this skill when the user asks for a report, business review, analysis
document, or any structured multi-page output.

## Execution Steps

1. **Plan the task**:
   Call `plan_task(request)` with the user's request. This returns a structured
   plan with phases and assigned agents. Show the plan to the user and ask for
   approval before proceeding.

2. **Execute each phase**:
   For each phase in the plan, call `execute_phase(plan_id, phase_id)`.
   After each phase, show progress and check the `decision` field:
   - `continue` — proceed to the next phase
   - `replan` — Athena has adjusted the remaining phases based on new findings
   - `clarify` — ask the user the clarification question before continuing
   - `complete` — all necessary data has been gathered, skip remaining phases

3. **Generate the report**:
   Call `generate_report(plan_id, title)` to compile all phase results into
   a professional Markdown document via Calliope.

4. **Deliver to user**:
   Present the report content and mention the file path so they can find it.

## Report Template
```markdown
# [Report Title]
**Prepared by:** Ira — Machinecraft AI Operating System
**Date:** [Date]
**Requested by:** [User]

## Executive Summary
[2-3 paragraph synthesis of all findings]

## [Section 1: e.g., Sales & Revenue]
[Agent findings with data tables and citations]

## [Section 2: e.g., Production]
[Agent findings with data tables and citations]

## Recommendations
[Actionable next steps based on findings]

## Sources & Methodology
[List of agents consulted, data sources queried, and any caveats]
```
