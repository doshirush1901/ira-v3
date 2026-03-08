---
description: >
  Sales pipeline skill — queries CRM data, analyzes deals, and provides
  pipeline insights. Use when the user asks about deals, pipeline, forecasts,
  or sales performance.
---

# Sales Pipeline Skill

## When to Use
Use this skill when the user asks about sales pipeline, specific deals,
forecasts, win/loss analysis, or revenue performance.

## Execution Steps

1. **Get pipeline overview**:
   Call `get_pipeline_summary` for the current state of the sales funnel.

2. **Query CRM for specifics**:
   Call `search_crm` with the user's specific query (deal name, customer, etc.).

3. **Delegate to specialist agents**:
   - `ask_agent("prometheus", ...)` for deal strategy and pipeline management
   - `ask_agent("tyche", ...)` for forecasting and win/loss prediction
   - `ask_agent("quotebuilder", ...)` if a quote or proposal is needed

4. **Cross-reference with finance**:
   For deal value or margin questions, also consult:
   - `ask_agent("plutus", ...)` for pricing and margin analysis

5. **Present findings**:
   Return a structured summary with deal tables and actionable recommendations.
