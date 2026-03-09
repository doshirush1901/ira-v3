# Agent Skill Coverage Matrix (v4)

Canonical source of truth:

- Skill definitions: `src/ira/skills/__init__.py`
- Skill handlers: `src/ira/skills/handlers.py`
- Agent coverage contract: `src/ira/skills/coverage.py`

## Coverage by Agent

| Agent | Required Skills | Optional Skills |
|:--|:--|:--|
| `athena` | `run_governance_check`, `audit_decision_log` | `generate_meeting_notes`, `search_knowledge_base` |
| `clio` | `search_knowledge_base`, `extract_key_facts`, `compare_documents`, `summarize_document` | `run_governance_check` |
| `prometheus` | `qualify_lead`, `generate_deal_summary`, `update_crm_record` | `forecast_pipeline`, `draft_outreach_email` |
| `plutus` | `calculate_quote`, `analyze_revenue`, `generate_invoice` | `forecast_pipeline`, `audit_decision_log` |
| `hermes` | `create_drip_sequence`, `draft_outreach_email`, `build_lead_report`, `schedule_campaign` | `generate_social_post` |
| `hephaestus` | `lookup_machine_spec`, `estimate_production_time` | `analyze_service_root_cause`, `generate_fat_plan` |
| `themis` | `lookup_employee`, `generate_org_chart` | `run_governance_check` |
| `calliope` | `draft_proposal`, `polish_text`, `translate_text`, `generate_meeting_notes` | `generate_social_post`, `run_governance_check` |
| `tyche` | `analyze_revenue`, `forecast_pipeline` | `generate_deal_summary` |
| `delphi` | `run_governance_check` | `extract_key_facts`, `audit_decision_log` |
| `sphinx` | `run_governance_check` | `audit_decision_log` |
| `vera` | `run_governance_check`, `audit_decision_log` | `validate_correction_consistency` |
| `sophia` | `audit_decision_log`, `validate_correction_consistency` | `summarize_document` |
| `iris` | `search_knowledge_base` | `extract_key_facts`, `run_governance_check` |
| `mnemosyne` | `validate_correction_consistency` | `audit_decision_log`, `search_knowledge_base` |
| `nemesis` | `audit_decision_log`, `validate_correction_consistency` | `run_governance_check` |
| `arachne` | `schedule_campaign`, `generate_social_post` | `draft_outreach_email` |
| `alexandros` | `search_knowledge_base`, `extract_key_facts`, `summarize_document` | `audit_decision_log` |
| `hera` | `evaluate_vendor_risk`, `compare_supplier_quotes`, `forecast_component_lead_time` | `audit_decision_log` |
| `atlas` | `generate_meeting_notes` | `audit_decision_log`, `search_knowledge_base` |
| `asclepius` | `triage_punch_list`, `generate_fat_plan`, `analyze_service_root_cause` | `run_governance_check` |
| `chiron` | `generate_deal_summary`, `draft_outreach_email` | `build_lead_report` |
| `cadmus` | `generate_social_post`, `draft_proposal` | `polish_text` |
| `quotebuilder` | `calculate_quote`, `draft_proposal`, `lookup_machine_spec` | `generate_invoice` |
| `artemis` | `qualify_lead`, `build_lead_report`, `search_knowledge_base` | `draft_outreach_email` |
| `gapper` | `search_knowledge_base`, `extract_key_facts`, `run_governance_check` | `audit_decision_log` |
| `mnemon` | `validate_correction_consistency`, `audit_decision_log` | `search_knowledge_base` |

## Newly Added Skill Primitives

- `evaluate_vendor_risk`
- `compare_supplier_quotes`
- `forecast_component_lead_time`
- `triage_punch_list`
- `generate_fat_plan`
- `analyze_service_root_cause`
- `run_governance_check`
- `audit_decision_log`
- `validate_correction_consistency`
