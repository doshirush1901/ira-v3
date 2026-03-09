# `agents/` — The Pantheon

27 specialist agents, each named after a figure from Greek mythology.
Every agent inherits from `BaseAgent` and implements `async def handle()`.

## Architecture

```
BaseAgent (base_agent.py)
  ├── ReAct loop (up to 8 iterations)
  ├── Auto-registered tools: recall_memory, store_memory, search_emails, etc.
  ├── SOUL.md preamble injected into every system prompt
  └── Inter-agent delegation via ask_agent tool
```

## Agent Roster

| Agent | File | Role |
|:------|:-----|:-----|
| Athena | `athena.py` | Orchestrator — routes, delegates, synthesizes |
| Prometheus | `prometheus.py` | Sales — CRM pipeline, deals, strategy |
| Hermes | `hermes.py` | Marketing — drip campaigns, lead intelligence |
| Plutus | `plutus.py` | Finance — pricing, revenue, margins |
| Hephaestus | `hephaestus.py` | Production — machine specs, manufacturing |
| Themis | `themis.py` | HR — employees, policies, org charts |
| Tyche | `tyche.py` | Forecasting — pipeline forecasts, win/loss |
| Clio | `clio.py` | Researcher — deep KB search, multi-source |
| Calliope | `calliope.py` | Writer — emails, proposals, reports |
| Vera | `vera.py` | Fact Checker — KB cross-referencing |
| Sphinx | `sphinx.py` | Gatekeeper — catches vague queries |
| Quotebuilder | `quotebuilder.py` | Quotes — structured formal quotes with specs |
| Mnemosyne | `mnemosyne.py` | Memory — long-term storage and retrieval |
| Nemesis | `nemesis.py` | Trainer — corrections, adversarial testing |
| Iris | `iris.py` | Intelligence — web search, news, company research |
| Delphi | `delphi.py` | Oracle — email classification, style simulation |
| Sophia | `sophia.py` | Reflector — post-interaction reflection |
| Alexandros | `alexandros.py` | Librarian — raw document archive fallback |
| Arachne | `arachne.py` | Content Scheduler — newsletters, LinkedIn |
| Cadmus | `cadmus.py` | Case Studies — NDA-safe content |
| Chiron | `chiron.py` | Sales Trainer — patterns, coaching notes |
| Atlas | `atlas.py` | Project Manager — logbook, schedules |
| Asclepius | `asclepius.py` | Quality — punch lists, FAT tracking |
| Hera | `hera.py` | Procurement — vendors, components, lead times |
| Mnemon | `mnemon.py` | Memory Guardian — correction ledger authority |
| Gapper | `gapper.py` | Gap Resolver — fills missing data |
| Artemis | `artemis.py` | Lead Hunter — email scanning, missed leads |

## Adding a New Agent

1. Create `{name}.py` inheriting from `BaseAgent`
2. Set `name`, `role`, `description`, `knowledge_categories`
3. Implement `_register_tools()` and `handle()`
4. Create `prompts/{name}_system.txt`
5. Register in `pantheon.py` → `_AGENT_CLASSES`
6. Add to the table above and in `prompts/athena_system.txt`
7. Write tests in `tests/test_agents.py`
