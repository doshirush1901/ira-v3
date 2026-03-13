# `tests/` — Test Suite

28 test files covering agents, brain modules, memory, body systems,
interfaces, and integrations. Framework: `pytest` + `pytest-asyncio`
with `asyncio_mode = "auto"`.

## Running Tests

```bash
poetry run pytest                        # full suite
poetry run pytest --cov=ira              # with coverage
poetry run pytest tests/test_agents.py   # specific file
poetry run pytest -k "test_clio"         # specific test
```

## Test Files

| File | Covers |
|:-----|:-------|
| `test_agents.py` | All 28 agents — routing, tool use, response quality |
| `test_brain.py` | Retriever, embeddings, entity extraction |
| `test_brain_modules.py` | Pricing, sales intelligence, correction store |
| `test_brain_fixes.py` | Regression tests for brain bug fixes |
| `test_memory.py` | All 10 memory subsystems |
| `test_react_loop.py` | ReAct loop iterations, tool dispatch |
| `test_systems.py` | Core body systems |
| `test_systems_extra.py` | Extended body systems |
| `test_interfaces.py` | FastAPI endpoints, CLI commands |
| `test_mcp_server.py` | MCP tool registration and execution |
| `test_crm.py` | CRM models, deal stages, contacts |
| `test_ingestion.py` | Document ingestion pipeline |
| `test_knowledge_graph.py` | Neo4j queries and entity linking |
| `test_skills.py` | Skill handlers |
| `test_context.py` | Context manager |
| `test_eval.py` | deepeval evaluation harness |
| `test_redis.py` | Redis cache operations |
| `test_circulatory.py` | Circulatory system sync |
| `test_dlp.py` | DLP PII redaction |
| `test_document_ai.py` | Document AI OCR |
| `test_drip_engine.py` | Drip campaign engine |
| `test_google_docs.py` | Google Docs integration |
| `test_pdfco.py` | PDF.co generation |
| `test_gap_resolver.py` | Gap resolution logic |
| `test_provenance.py` | Source provenance tracking |
| `test_anti_hallucination.py` | Hallucination detection |
| `test_task_orchestrator.py` | Agent Loop orchestration |
| `test_voyage_rerank.py` | Voyage reranking |

## Conventions

- Mock all external services (LLM APIs, Qdrant, Neo4j, Mem0).
- Mock `LLMClient.generate_structured` and `generate_text`, not raw httpx.
- Return Pydantic model instances from mocks, not JSON strings.
- Shared fixtures live in `conftest.py`.
