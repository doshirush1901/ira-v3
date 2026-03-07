"""Tests for the ira.brain package.

Covers all eight brain modules: EmbeddingService, QdrantManager,
DocumentIngestor, UnifiedRetriever, DeterministicRouter,
MachineIntelligence, PricingEngine, and SalesIntelligence.

External services (Voyage API, Qdrant, Neo4j, OpenAI, Newsdata) are
mocked so the suite runs fully offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ira.brain.deterministic_router import DeterministicRouter, IntentCategory
from ira.brain.document_ingestor import chunk_text
from ira.data.models import Contact, KnowledgeItem


# ── helpers ──────────────────────────────────────────────────────────────────

VECTOR_DIM = 8


def _fake_vector() -> list[float]:
    return [0.1] * VECTOR_DIM


def _fake_vectors(n: int) -> list[list[float]]:
    return [[0.1 * (i + 1)] * VECTOR_DIM for i in range(n)]


def _mock_settings():
    """Return a MagicMock that mimics get_settings() for brain modules."""
    s = MagicMock()
    s.llm.openai_api_key.get_secret_value.return_value = "test-openai-key"
    s.llm.openai_model = "gpt-4.1"
    s.external_apis.api_key.get_secret_value.return_value = ""
    return s


def _mock_retriever():
    """Return an AsyncMock that mimics UnifiedRetriever."""
    r = AsyncMock()
    r.search = AsyncMock(return_value=[
        {"content": "kb result", "score": 0.9, "source": "file.pdf", "metadata": {}},
    ])
    r.search_by_category = AsyncMock(return_value=[
        {"content": "category result", "score": 0.85, "source": "cat.pdf", "metadata": {}},
    ])
    return r


def _sample_contact(**overrides) -> Contact:
    defaults = dict(
        name="John Doe",
        email="john@example.com",
        company="Acme Corp",
        region="MENA",
        industry="Construction",
        source="web_form",
        score=25.0,
    )
    defaults.update(overrides)
    return Contact(**defaults)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def embedding_config():
    from pydantic import SecretStr

    from ira.config import EmbeddingConfig

    return EmbeddingConfig(api_key=SecretStr("test-key"), model="voyage-3")


@pytest.fixture()
def embedding_service(embedding_config, tmp_path):
    from ira.brain.embeddings import EmbeddingService

    return EmbeddingService(
        config=embedding_config,
        cache_size=64,
        cache_path=str(tmp_path / "embedding_cache.db"),
    )


@pytest.fixture()
def qdrant_manager(embedding_service):
    from ira.brain.qdrant_manager import QdrantManager
    from ira.config import QdrantConfig

    cfg = QdrantConfig(url="http://localhost:6333", collection="test_collection")
    mgr = QdrantManager(embedding_service=embedding_service, config=cfg)
    mgr._client = AsyncMock()
    return mgr


@pytest.fixture()
def router():
    return DeterministicRouter()


@pytest.fixture()
def mock_retriever_fixture():
    return _mock_retriever()


# ═════════════════════════════════════════════════════════════════════════════
# 1. EmbeddingService
# ═════════════════════════════════════════════════════════════════════════════


class TestEmbeddingService:

    @pytest.mark.asyncio
    async def test_embed_texts_returns_correct_dimensions(self, embedding_service):
        texts = ["hello world", "foo bar"]
        fake = _fake_vectors(len(texts))

        with patch.object(embedding_service, "_call_api", new_callable=AsyncMock, return_value=fake):
            result = await embedding_service.embed_texts(texts)

        assert len(result) == len(texts)
        for vec in result:
            assert len(vec) == VECTOR_DIM

    @pytest.mark.asyncio
    async def test_embed_texts_empty_list(self, embedding_service):
        result = await embedding_service.embed_texts([])
        assert result == []

    @pytest.mark.asyncio
    async def test_batching_with_more_than_128_texts(self, embedding_service):
        n = 260
        texts = [f"text_{i}" for i in range(n)]
        call_count = 0

        async def counting_api(batch, *, input_type):
            nonlocal call_count
            call_count += 1
            assert len(batch) <= 128
            return _fake_vectors(len(batch))

        with patch.object(embedding_service, "_call_api", side_effect=counting_api):
            result = await embedding_service.embed_texts(texts)

        assert len(result) == n
        assert call_count == 3  # ceil(260 / 128)

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_api_call(self, embedding_service):
        text = "cached text"
        fake = _fake_vectors(1)

        with patch.object(
            embedding_service, "_call_api", new_callable=AsyncMock, return_value=fake,
        ) as mock_api:
            first = await embedding_service.embed_texts([text])
            second = await embedding_service.embed_texts([text])

        assert first == second
        mock_api.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_query_returns_single_vector(self, embedding_service):
        fake = [_fake_vector()]

        with patch.object(embedding_service, "_call_api", new_callable=AsyncMock, return_value=fake):
            result = await embedding_service.embed_query("test query")

        assert isinstance(result, list)
        assert len(result) == VECTOR_DIM

    @pytest.mark.asyncio
    async def test_embed_query_uses_query_input_type(self, embedding_service):
        fake = [_fake_vector()]

        with patch.object(
            embedding_service, "_call_api", new_callable=AsyncMock, return_value=fake,
        ) as mock_api:
            await embedding_service.embed_query("test")

        mock_api.assert_awaited_once_with(["test"], input_type="query")


# ═════════════════════════════════════════════════════════════════════════════
# 2. QdrantManager
# ═════════════════════════════════════════════════════════════════════════════


class TestQdrantManager:

    @pytest.mark.asyncio
    async def test_ensure_collection_creates_when_missing(self, qdrant_manager):
        qdrant_manager._client.collection_exists = AsyncMock(return_value=False)
        qdrant_manager._client.create_collection = AsyncMock()

        await qdrant_manager.ensure_collection("test_col", vector_size=VECTOR_DIM)

        qdrant_manager._client.collection_exists.assert_awaited_once_with("test_col")
        qdrant_manager._client.create_collection.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_collection_skips_when_exists(self, qdrant_manager):
        qdrant_manager._client.collection_exists = AsyncMock(return_value=True)
        qdrant_manager._client.create_collection = AsyncMock()

        await qdrant_manager.ensure_collection("test_col")

        qdrant_manager._client.create_collection.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert_items(self, qdrant_manager):
        items = [
            KnowledgeItem(source="test.txt", source_category="test_cat", content=f"content {i}")
            for i in range(3)
        ]

        with patch.object(
            qdrant_manager._embeddings, "embed_texts",
            new_callable=AsyncMock, return_value=_fake_vectors(3),
        ):
            qdrant_manager._client.upsert = AsyncMock()
            count = await qdrant_manager.upsert_items(items)

        assert count == 3
        qdrant_manager._client.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_empty_list(self, qdrant_manager):
        count = await qdrant_manager.upsert_items([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_search_returns_dicts(self, qdrant_manager):
        fake_hit = MagicMock()
        fake_hit.payload = {
            "content": "result text",
            "source": "file.pdf",
            "source_category": "specs",
            "metadata": {},
        }
        fake_hit.score = 0.95

        with patch.object(
            qdrant_manager._embeddings, "embed_query",
            new_callable=AsyncMock, return_value=_fake_vector(),
        ):
            qdrant_manager._client.search = AsyncMock(return_value=[fake_hit])
            results = await qdrant_manager.search("test query", limit=5)

        assert len(results) == 1
        assert results[0]["content"] == "result text"
        assert results[0]["score"] == 0.95
        assert results[0]["source"] == "file.pdf"

    @pytest.mark.asyncio
    async def test_hybrid_search_with_category(self, qdrant_manager):
        fake_hit = MagicMock()
        fake_hit.payload = {"content": "filtered", "source": "s", "source_category": "cat", "metadata": {}}
        fake_hit.score = 0.8

        with patch.object(
            qdrant_manager._embeddings, "embed_query",
            new_callable=AsyncMock, return_value=_fake_vector(),
        ):
            qdrant_manager._client.search = AsyncMock(return_value=[fake_hit])
            results = await qdrant_manager.hybrid_search("query", source_category="cat")

        assert len(results) == 1
        qdrant_manager._client.search.assert_awaited_once()
        call_kwargs = qdrant_manager._client.search.call_args
        assert call_kwargs.kwargs.get("query_filter") is not None


# ═════════════════════════════════════════════════════════════════════════════
# 3. DocumentIngestor — chunking
# ═════════════════════════════════════════════════════════════════════════════


class TestChunking:

    def test_short_text_returns_single_chunk(self):
        text = "Hello world."
        chunks = chunk_text(text, chunk_size=512, overlap=128)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_produces_multiple_chunks(self):
        text = "word " * 1000
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) > 0

    def test_chunk_size_respected(self):
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        text = "token " * 500
        chunks = chunk_text(text, chunk_size=100, overlap=20)

        for chunk in chunks[:-1]:
            assert len(enc.encode(chunk)) == 100

    def test_overlap_produces_shared_tokens(self):
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        text = " ".join(f"w{i}" for i in range(300))
        chunks = chunk_text(text, chunk_size=50, overlap=10)

        assert len(chunks) >= 2
        tokens_0 = enc.encode(chunks[0])
        tokens_1 = enc.encode(chunks[1])
        # Last 10 tokens of chunk 0 should equal first 10 tokens of chunk 1
        assert tokens_0[-10:] == tokens_1[:10]

    def test_empty_text(self):
        chunks = chunk_text("", chunk_size=100, overlap=20)
        assert len(chunks) == 1


# ═════════════════════════════════════════════════════════════════════════════
# 4. UnifiedRetriever
# ═════════════════════════════════════════════════════════════════════════════


class TestUnifiedRetriever:

    @pytest.fixture()
    def retriever(self):
        from ira.brain.retriever import UnifiedRetriever

        mock_qdrant = AsyncMock()
        mock_graph = AsyncMock()

        mock_qdrant.hybrid_search = AsyncMock(return_value=[
            {"content": "qdrant result", "score": 0.9, "source": "file.pdf", "metadata": {}},
        ])
        mock_graph.find_related_entities = AsyncMock(
            return_value={"nodes": [], "relationships": []},
        )

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": 0, "text": "qdrant result", "score": 0.95, "meta": {
                "source": "file.pdf", "source_type": "qdrant", "metadata": {},
            }},
        ]

        with patch("ira.brain.retriever.Ranker", return_value=mock_ranker), \
             patch("ira.brain.retriever.get_settings", return_value=_mock_settings()):
            ret = UnifiedRetriever(mock_qdrant, mock_graph)

        ret._ranker = mock_ranker
        return ret

    @pytest.mark.asyncio
    async def test_search_returns_results(self, retriever):
        results = await retriever.search("test query", sources=["qdrant"], limit=5)
        assert len(results) >= 1
        assert results[0]["content"] == "qdrant result"

    @pytest.mark.asyncio
    async def test_search_returns_empty_for_no_results(self, retriever):
        retriever._qdrant.hybrid_search = AsyncMock(return_value=[])
        results = await retriever.search("nothing", sources=["qdrant"], limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_tags_source_type(self, retriever):
        results = await retriever.search("test", sources=["qdrant"], limit=5)
        assert results[0].get("source_type") == "qdrant"

    @pytest.mark.asyncio
    async def test_search_by_category_delegates_to_qdrant(self, retriever):
        retriever._qdrant.hybrid_search = AsyncMock(return_value=[
            {"content": "cat result", "score": 0.8, "source": "s", "metadata": {}},
        ])
        retriever._ranker.rerank.return_value = [
            {"id": 0, "text": "cat result", "score": 0.85, "meta": {
                "source": "s", "source_type": "qdrant", "metadata": {},
            }},
        ]

        results = await retriever.search_by_category("query", "specs", limit=3)
        assert len(results) >= 1
        retriever._qdrant.hybrid_search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_decompose_falls_back_without_openai_key(self, retriever):
        retriever._openai_key = ""
        results = await retriever.decompose_and_search("complex question")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_handles_backend_failure(self, retriever):
        retriever._qdrant.hybrid_search = AsyncMock(side_effect=RuntimeError("boom"))
        results = await retriever.search("test", sources=["qdrant"], limit=5)
        assert results == []


# ═════════════════════════════════════════════════════════════════════════════
# 5. DeterministicRouter
# ═════════════════════════════════════════════════════════════════════════════


class TestDeterministicRouter:

    @pytest.mark.parametrize(
        "query, expected",
        [
            ("Show me the sales pipeline and all active deals", IntentCategory.SALES_PIPELINE),
            ("How many leads are in the CRM?", IntentCategory.SALES_PIPELINE),
            ("I need a quote for the PF1-C line", IntentCategory.QUOTE_REQUEST),
            ("What is the price of the AM-Series?", IntentCategory.QUOTE_REQUEST),
            ("Give me the PF2 specs and technical details", IntentCategory.MACHINE_SPECS),
            ("What are the RF-100 specifications?", IntentCategory.MACHINE_SPECS),
            ("Show me the revenue forecast and cash flow", IntentCategory.FINANCE_REVIEW),
            ("What's our profit margin this quarter?", IntentCategory.FINANCE_REVIEW),
            ("How many employees do we have? HR headcount", IntentCategory.HR_OVERVIEW),
            ("What's the production lead time for assembly?", IntentCategory.PRODUCTION_STATUS),
            ("Launch a new drip marketing campaign", IntentCategory.MARKETING_CAMPAIGN),
            ("Send a newsletter email blast", IntentCategory.MARKETING_CAMPAIGN),
            ("Customer filed a warranty complaint", IntentCategory.CUSTOMER_SERVICE),
            ("Do market analysis on competitor trends", IntentCategory.RESEARCH),
        ],
    )
    def test_classify_intent(self, router, query, expected):
        result = router.classify_intent(query)
        assert result == expected, f"Expected {expected} for '{query}', got {result}"

    def test_classify_returns_none_for_ambiguous_query(self, router):
        assert router.classify_intent("hello, how are you today?") is None

    def test_get_routing_returns_required_agents(self, router):
        routing = router.get_routing(IntentCategory.QUOTE_REQUEST)
        assert "prometheus" in routing["required_agents"]
        assert "plutus" in routing["required_agents"]
        assert "hephaestus" in routing["required_agents"]
        assert "pricing_engine" in routing["required_tools"]

    def test_get_routing_for_all_intents(self, router):
        for intent in IntentCategory:
            routing = router.get_routing(intent)
            assert "intent" in routing
            assert isinstance(routing["required_agents"], list)
            assert len(routing["required_agents"]) >= 1

    def test_route_convenience_method(self, router):
        result = router.route("Show me the CRM pipeline deals")
        assert result is not None
        assert result["intent"] == "SALES_PIPELINE"

    def test_route_returns_none_for_unknown(self, router):
        assert router.route("tell me a joke") is None


# ═════════════════════════════════════════════════════════════════════════════
# 6. MachineIntelligence
# ═════════════════════════════════════════════════════════════════════════════


class TestMachineIntelligence:

    @pytest.fixture()
    def machine_intel(self, mock_retriever_fixture, tmp_path):
        from ira.brain.machine_intelligence import MachineIntelligence

        knowledge = {
            "machine_catalog": {
                "PF1-C": {
                    "category": "Panel Forming",
                    "description": "Continuous panel forming line.",
                    "key_features": ["Continuous lamination", "PU / PIR core"],
                },
            },
            "truth_hints": {
                "PF1-C lead time": "16-20 weeks",
                "AM-Series max material thickness": "12 mm",
            },
        }
        knowledge_file = tmp_path / "machine_knowledge.json"
        knowledge_file.write_text(json.dumps(knowledge))

        with patch("ira.brain.machine_intelligence.get_settings", return_value=_mock_settings()):
            mi = MachineIntelligence(
                retriever=mock_retriever_fixture,
                knowledge_path=knowledge_file,
            )
        return mi

    def test_catalog_loaded(self, machine_intel):
        assert "PF1-C" in machine_intel.machine_catalog
        assert machine_intel.machine_catalog["PF1-C"]["category"] == "Panel Forming"

    def test_truth_hints_loaded(self, machine_intel):
        assert "PF1-C lead time" in machine_intel.truth_hints
        assert machine_intel.truth_hints["PF1-C lead time"] == "16-20 weeks"

    @pytest.mark.asyncio
    async def test_get_machine_specs_merges_sources(self, machine_intel):
        specs = await machine_intel.get_machine_specs("PF1-C")

        assert specs["model"] == "PF1-C"
        assert specs["catalog"]["category"] == "Panel Forming"
        assert "PF1-C lead time" in specs["truth_hints"]
        assert isinstance(specs["knowledge_base"], list)

    @pytest.mark.asyncio
    async def test_get_machine_specs_unknown_model(self, machine_intel):
        specs = await machine_intel.get_machine_specs("UNKNOWN-99")
        assert specs["model"] == "UNKNOWN-99"
        assert specs["catalog"] == {}
        assert specs["truth_hints"] == {}

    @pytest.mark.asyncio
    async def test_recommend_machine_without_openai(self, machine_intel):
        machine_intel._openai_key = ""
        result = await machine_intel.recommend_machine({"material": "steel", "thickness": "0.5mm"})
        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_recommend_machine_with_llm(self, machine_intel):
        llm_response = json.dumps([
            {"model": "PF1-C", "reason": "Best fit", "caveats": "None", "budget_indication": "$500k"},
        ])
        with patch.object(machine_intel, "_llm_call", new_callable=AsyncMock, return_value=llm_response):
            result = await machine_intel.recommend_machine({"material": "steel"})

        assert result[0]["model"] == "PF1-C"

    @pytest.mark.asyncio
    async def test_compare_machines(self, machine_intel):
        with patch.object(
            machine_intel, "_llm_call", new_callable=AsyncMock, return_value="| Feature | PF1-C | PF2 |",
        ):
            result = await machine_intel.compare_machines("PF1-C", "PF2")

        assert "PF1-C" in result


# ═════════════════════════════════════════════════════════════════════════════
# 7. PricingEngine
# ═════════════════════════════════════════════════════════════════════════════


class TestPricingEngine:

    @pytest.fixture()
    def pricing_engine(self, mock_retriever_fixture):
        from ira.brain.pricing_engine import PricingEngine

        with patch("ira.brain.pricing_engine.get_settings", return_value=_mock_settings()):
            pe = PricingEngine(retriever=mock_retriever_fixture)
        return pe

    @pytest.mark.asyncio
    async def test_estimate_price_returns_structure(self, pricing_engine):
        llm_response = json.dumps({
            "estimated_price": {"low": 100000, "mid": 150000, "high": 200000, "currency": "USD"},
            "confidence": "medium",
            "reasoning": "Based on similar quotes",
        })
        with patch.object(pricing_engine, "_llm_call", new_callable=AsyncMock, return_value=llm_response):
            result = await pricing_engine.estimate_price("PF1-C", {"panels": "PU"})

        assert "estimated_price" in result
        assert result["estimated_price"]["mid"] == 150000
        assert "similar_quotes" in result
        assert isinstance(result["similar_quotes"], list)

    @pytest.mark.asyncio
    async def test_estimate_price_handles_bad_llm_response(self, pricing_engine):
        with patch.object(pricing_engine, "_llm_call", new_callable=AsyncMock, return_value="not json"):
            result = await pricing_engine.estimate_price("PF1-C", {})

        assert result["confidence"] == "low"
        assert "similar_quotes" in result

    @pytest.mark.asyncio
    async def test_analyze_quote_history_without_crm(self, pricing_engine):
        result = await pricing_engine.analyze_quote_history({"region": "MENA"})
        assert result["source"] == "knowledge_base"
        assert "relevant_excerpts" in result

    @pytest.mark.asyncio
    async def test_analyze_quote_history_with_crm(self, pricing_engine):
        mock_crm = AsyncMock()
        mock_crm.get_deals_by_filter = AsyncMock(return_value=[
            {"value": 100000, "stage": "WON"},
            {"value": 200000, "stage": "WON"},
            {"value": 50000, "stage": "LOST"},
        ])
        pricing_engine._crm = mock_crm

        result = await pricing_engine.analyze_quote_history({"region": "EU"})

        assert result["total_deals"] == 3
        assert result["won_count"] == 2
        assert result["lost_count"] == 1
        assert result["win_rate"] == pytest.approx(2 / 3)

    @pytest.mark.asyncio
    async def test_generate_quote_content(self, pricing_engine):
        contact = _sample_contact()
        estimate_json = json.dumps({
            "estimated_price": {"low": 100000, "mid": 150000, "high": 200000, "currency": "USD"},
            "confidence": "medium",
            "reasoning": "test",
        })
        quote_json = json.dumps({
            "reference_number": "QT-20260306-001",
            "greeting": "Dear John",
            "scope_of_supply": ["PF1-C line"],
            "technical_summary": "A panel forming line.",
            "commercial_terms": {"price": "TBD"},
            "closing": "Best regards",
        })

        call_count = 0

        async def mock_llm(system, user):
            nonlocal call_count
            call_count += 1
            return estimate_json if call_count == 1 else quote_json

        with patch.object(pricing_engine, "_llm_call", side_effect=mock_llm):
            result = await pricing_engine.generate_quote_content(contact, "PF1-C", {"core": "PU"})

        assert "greeting" in result
        assert result["reference_number"] == "QT-20260306-001"


# ═════════════════════════════════════════════════════════════════════════════
# 8. SalesIntelligence
# ═════════════════════════════════════════════════════════════════════════════


class TestSalesIntelligence:

    @pytest.fixture()
    def sales_intel(self, mock_retriever_fixture):
        from ira.brain.sales_intelligence import SalesIntelligence

        with patch("ira.brain.sales_intelligence.get_settings", return_value=_mock_settings()):
            si = SalesIntelligence(retriever=mock_retriever_fixture)
        return si

    @pytest.mark.asyncio
    async def test_qualify_lead(self, sales_intel):
        contact = _sample_contact()
        llm_response = json.dumps({
            "score": 75,
            "qualification_level": "HOT",
            "buying_signals": ["Specific machine mentioned"],
            "risk_factors": [],
            "reasoning": "Strong buying intent",
        })

        with patch.object(sales_intel, "_llm_call", new_callable=AsyncMock, return_value=llm_response):
            result = await sales_intel.qualify_lead(contact, "I need a PF1-C quote urgently")

        assert result["score"] == 75
        assert result["qualification_level"] == "HOT"

    @pytest.mark.asyncio
    async def test_qualify_lead_handles_bad_llm(self, sales_intel):
        contact = _sample_contact()

        with patch.object(sales_intel, "_llm_call", new_callable=AsyncMock, return_value="not json"):
            result = await sales_intel.qualify_lead(contact, "inquiry")

        assert result["qualification_level"] == "COLD"
        assert result["score"] == 0

    @pytest.mark.asyncio
    async def test_score_customer_health_without_crm(self, sales_intel):
        with patch.object(
            sales_intel, "_llm_call", new_callable=AsyncMock,
            return_value=json.dumps({"health_score": 60, "trend": "stable", "reasoning": "ok"}),
        ):
            result = await sales_intel.score_customer_health(uuid4())

        assert result["health_score"] == 60

    @pytest.mark.asyncio
    async def test_score_customer_health_with_crm(self, sales_intel):
        mock_crm = AsyncMock()
        mock_crm.get_interactions_for_contact = AsyncMock(return_value=[
            {"summary": "Call", "created_at": "2026-03-01"},
        ])
        mock_crm.get_deals_for_contact = AsyncMock(return_value=[
            {"title": "PF1-C deal", "stage": "PROPOSAL"},
        ])
        sales_intel._crm = mock_crm

        with patch.object(
            sales_intel, "_llm_call", new_callable=AsyncMock,
            return_value=json.dumps({"health_score": 80, "trend": "improving", "reasoning": "active"}),
        ):
            result = await sales_intel.score_customer_health(uuid4())

        assert result["health_score"] == 80
        mock_crm.get_interactions_for_contact.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_identify_stale_leads_without_crm(self, sales_intel):
        result = await sales_intel.identify_stale_leads(days_threshold=14)
        assert result == []

    @pytest.mark.asyncio
    async def test_identify_stale_leads_with_crm(self, sales_intel):
        mock_crm = AsyncMock()
        mock_crm.get_stale_leads = AsyncMock(return_value=[
            {"name": "Jane", "email": "jane@co.com", "last_contact": "2026-02-15"},
        ])
        sales_intel._crm = mock_crm

        llm_response = json.dumps([{
            "contact_name": "Jane",
            "days_since_contact": 19,
            "strategy": "Send case study",
            "suggested_channel": "EMAIL",
            "message_hook": "Hi Jane, thought you might find this relevant",
        }])

        with patch.object(sales_intel, "_llm_call", new_callable=AsyncMock, return_value=llm_response):
            result = await sales_intel.identify_stale_leads(days_threshold=14)

        assert len(result) == 1
        assert result[0]["contact_name"] == "Jane"

    @pytest.mark.asyncio
    async def test_generate_lead_intelligence(self, sales_intel):
        llm_response = json.dumps({
            "company_summary": "Acme builds things",
            "recent_news": ["Acme wins contract"],
            "industry_trends": ["Green building"],
            "key_personnel": [{"name": "CEO", "role": "CEO"}],
            "opportunities": ["Expansion"],
            "risks": ["Budget cuts"],
        })

        with patch.object(sales_intel, "_llm_call", new_callable=AsyncMock, return_value=llm_response):
            result = await sales_intel.generate_lead_intelligence("Acme Corp")

        assert result["company_summary"] == "Acme builds things"
        assert len(result["recent_news"]) == 1

    @pytest.mark.asyncio
    async def test_generate_lead_intelligence_handles_bad_llm(self, sales_intel):
        with patch.object(sales_intel, "_llm_call", new_callable=AsyncMock, return_value="not json"):
            result = await sales_intel.generate_lead_intelligence("Acme Corp")

        assert "raw" in result
