# `systems/` — Body Systems

21 modules organized around a biological metaphor. The metaphor enforces
separation of concerns — each system has a clear boundary and purpose.

## Core Body Systems

| Module | Metaphor | Purpose |
|:-------|:---------|:--------|
| `sensory.py` | Eyes & ears | Contact resolution, emotion detection, metadata extraction |
| `digestive.py` | Stomach | Email processing, document summarization, nutrient extraction |
| `circulatory.py` | Bloodstream | Cross-system data sync, heartbeat scheduling |
| `immune.py` | Immune system | Hallucination detection, fact verification, safety filters |
| `respiratory.py` | Lungs | Background health checks, system monitoring, vital signs |
| `voice.py` | Vocal cords | Output shaping for channel and recipient |

## Extended Systems

| Module | Purpose |
|:-------|:--------|
| `redis_cache.py` | Response dedup, message stream persistence, caching |
| `document_ai.py` | OCR for scanned PDFs via Google Document AI |
| `dlp.py` | PII redaction via Google Cloud DLP |
| `google_docs.py` | Read, write, export Google Docs |
| `pdfco.py` | HTML-to-PDF generation and text extraction |
| `learning_hub.py` | Feedback processing, knowledge gap analysis |
| `board_meeting.py` | Multi-agent collaborative discussions |
| `drip_engine.py` | Automated multi-step email campaigns |
| `data_event_bus.py` | Typed event system for cross-store sync |
| `crm_enricher.py` | Multi-agent CRM enrichment pipeline |
| `crm_populator.py` | Contact classification and import |
| `task_orchestrator.py` | Agent Loop: Plan → Execute → Observe → Compile |

## Lightweight Integrations

`endocrine.py` (behavioral modifiers) and `musculoskeletal.py` (action
recording) are wired into the pipeline as service-key integrations rather
than standalone system files.
