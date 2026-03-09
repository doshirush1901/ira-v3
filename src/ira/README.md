# `src/ira/` — Core Package

This is the main Python package for Ira v3. Everything the system does
lives here.

## Directory Layout

```
ira/
├── agents/          27 specialist agents + BaseAgent
├── brain/           Knowledge retrieval, embeddings, graph, routing,
│                    entity extraction, guardrails (32 modules)
├── memory/          10 memory subsystems + dream mode + goal sweep
├── systems/         Body-system metaphor (21 modules)
├── interfaces/      FastAPI server, CLI, MCP server, email processor, dashboard
├── services/        LLMClient (OpenAI + Anthropic with Langfuse tracing)
├── schemas/         Pydantic models for structured LLM outputs
├── skills/          Shared skill handlers
├── middleware/      Auth + request context
├── data/            CRM, quote, and vendor ORM models
├── templates/       HTML templates (dashboard)
├── pipeline.py      11-stage request pipeline
├── pipeline_loop.py Agent Loop: Plan → Execute → Observe → Compile
├── pantheon.py      Agent orchestrator + routing
├── config.py        Pydantic settings (all config from .env)
├── context.py       Unified context manager
├── message_bus.py   Inter-agent pub/sub messaging
├── prompt_loader.py Prompt template loading + SOUL.md preamble
├── service_keys.py  Service registry keys
└── exceptions.py    Custom exception hierarchy
```

## Key Entry Points

| Module | Purpose |
|:-------|:--------|
| `pipeline.py` | Every request flows through the 11-stage `RequestPipeline` |
| `pantheon.py` | Registers all 27 agents, handles routing + delegation |
| `config.py` | Single `IraConfig` Pydantic settings class — all env vars |
| `interfaces/server.py` | FastAPI app with REST + SSE streaming endpoints |
| `interfaces/cli.py` | Typer CLI (`ira chat`, `ira ask`, `ira dream`, etc.) |
| `interfaces/mcp_server.py` | FastMCP server exposing 35+ tools for Cursor/Claude |

## Conventions

- `from __future__ import annotations` at the top of every module.
- stdlib `logging` only — `logger = logging.getLogger(__name__)`.
- Type hints on all public functions.
- LLM calls go through `services/llm_client.py`, never raw httpx.
- System prompts live in `prompts/`, loaded via `prompt_loader.load_prompt()`.
