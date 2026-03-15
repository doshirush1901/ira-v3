"""Master request-processing pipeline — from raw input to shaped response.

Every inbound message, regardless of channel, flows through
:func:`RequestPipeline.process_request`.  The pipeline is intentionally
linear so that each step can be individually logged, timed, and tested.

Steps
-----
1. **PERCEIVE** — SensorySystem resolves identity, emotional state, history.
2. **REMEMBER** — ConversationMemory, coreference resolution, goals.
2.5. **FAST PATH** — Regex classifier for greetings, identity, thanks, farewells.
     Matched queries skip stages 3-8 and return in 1-3 seconds.
2.7. **SPHINX GATE** — Sphinx evaluates query clarity.  Vague queries get
     clarifying questions returned immediately via ``[CLARIFY]`` prefix.
3. **ROUTE (Fast)** — DeterministicRouter for keyword-matched intents.
3.5. **TRUTH HINTS** — Canned answers for known factual questions.
4. **ROUTE (Procedure)** — ProceduralMemory for learned response patterns.
5. **ROUTE (LLM)** — Athena for open-ended LLM-based routing.
5.5. **ENRICH CONTEXT** — AdaptiveStyle, RealTimeObserver, Endocrine, etc.
6. **EXECUTE** — Routed agent(s) produce a raw response.
6.4. **FAITHFULNESS GATE** — ``check_faithfulness()`` verifies claims against KB.
     Appends caveat when score < threshold.  Also runs confidentiality and
     competitor checks for LLM-routed responses.
7. **ASSESS** — Metacognition evaluates confidence and adds caveats.
7.1. **CONFIDENCE FLOOR** — Replaces response with honest "I don't know" when
     state is UNKNOWN or confidence is below the floor.
8. **REFLECT** — InnerVoice surfaces optional reflections.
9. **SHAPE** — VoiceSystem formats for channel and recipient.
10. **LEARN** — Record in ConversationMemory, CRM, MusculoskeletalSystem; trigger Sophia.
11. **RETURN** — Final shaped response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from typing import Any

from langfuse.decorators import observe

from ira.data.models import Channel, Contact, Direction, PipelineContextModel
from ira.exceptions import DatabaseError, IraError, LLMError, ToolExecutionError

logger = logging.getLogger(__name__)


class RequestPipeline:
    """Stateful pipeline that holds references to every subsystem.

    Construct once at application startup (e.g. in the FastAPI lifespan)
    and reuse for every request.
    """

    def __init__(
        self,
        *,
        sensory: Any,
        conversation_memory: Any,
        relationship_memory: Any | None = None,
        goal_manager: Any | None = None,
        procedural_memory: Any | None = None,
        metacognition: Any | None = None,
        inner_voice: Any | None = None,
        pantheon: Any,
        voice: Any,
        endocrine: Any | None = None,
        crm: Any | None = None,
        musculoskeletal: Any | None = None,
        unified_context: Any | None = None,
        adaptive_style: Any | None = None,
        realtime_observer: Any | None = None,
        power_level_tracker: Any | None = None,
        redis_cache: Any | None = None,
        episodic_memory: Any | None = None,
        long_term_memory: Any | None = None,
        tool_stats_tracker: Any | None = None,
        agent_journal: Any | None = None,
    ) -> None:
        self._sensory = sensory
        self._conversation = conversation_memory
        self._relationship = relationship_memory
        self._goals = goal_manager
        self._procedural = procedural_memory
        self._metacognition = metacognition
        self._inner_voice = inner_voice
        self._pantheon = pantheon
        self._voice = voice
        self._endocrine = endocrine
        self._crm = crm
        self._musculoskeletal = musculoskeletal
        self._unified_ctx = unified_context
        self._adaptive_style = adaptive_style
        self._realtime_observer = realtime_observer
        self._power_level_tracker = power_level_tracker
        self._redis = redis_cache
        self._episodic = episodic_memory
        self._long_term = long_term_memory
        self._tool_stats_tracker = tool_stats_tracker
        self._agent_journal = agent_journal

        self._router = pantheon.router
        self._pending_clarifications: dict[str, dict[str, Any]] = {}
        self._recent_messages: dict[str, tuple[str, float]] = {}
        self._state_lock = asyncio.Lock()
        self._request_semaphore = asyncio.Semaphore(5)
        self._stage_timings: deque[dict[str, Any]] = deque(maxlen=100)

        self._load_pending_clarifications()

    _REQUEST_TIMEOUT = 360
    _CLARIFICATION_REDIS_KEY = "ira:pending_clarifications"

    def _load_pending_clarifications(self) -> None:
        """Restore pending clarifications from Redis on startup."""
        if self._redis is None:
            return
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return
        except RuntimeError:
            return

    async def _persist_clarification(self, sender_id: str, data: dict[str, Any]) -> None:
        """Store a pending clarification in Redis for cross-invocation persistence."""
        if self._redis is None:
            return
        try:
            import json as _json
            await self._redis.hset(
                self._CLARIFICATION_REDIS_KEY, sender_id, _json.dumps(data),
            )
        except Exception:
            logger.warning("Failed to persist clarification to Redis", exc_info=True)

    async def _pop_clarification(self, sender_id: str) -> dict[str, Any] | None:
        """Pop a pending clarification from both memory and Redis."""
        async with self._state_lock:
            result = self._pending_clarifications.pop(sender_id, None)
        if result is not None:
            if self._redis is not None:
                try:
                    await self._redis.hdel(self._CLARIFICATION_REDIS_KEY, sender_id)
                except Exception:
                    logger.warning("Failed to remove clarification from Redis", exc_info=True)
            return result
        if self._redis is not None:
            try:
                import json as _json
                raw = await self._redis.hget(self._CLARIFICATION_REDIS_KEY, sender_id)
                if raw:
                    await self._redis.hdel(self._CLARIFICATION_REDIS_KEY, sender_id)
                    return _json.loads(raw)
            except Exception:
                logger.warning("Failed to load clarification from Redis", exc_info=True)
        return None

    def get_recent_stage_timings(self, n: int = 24) -> list[dict[str, Any]]:
        """Return the last n pipeline runs' per-stage durations (seconds) and timestamps."""
        recent = list(self._stage_timings)
        return recent[-n:] if len(recent) > n else recent

    # ── Public entry point ────────────────────────────────────────────────

    @observe(name="pipeline.process_request")
    async def process_request(
        self,
        raw_input: str,
        channel: str,
        sender_id: str,
        metadata: dict[str, Any] | None = None,
        on_progress: Any | None = None,
    ) -> tuple[str, list[str]]:
        """Run the full 11-step pipeline with concurrency and timeout guards."""
        async with self._request_semaphore:
            try:
                from ira.config import get_settings
                _timeout = get_settings().app.pipeline_timeout
                return await asyncio.wait_for(
                    self._process_request_inner(
                        raw_input, channel, sender_id, metadata, on_progress,
                    ),
                    timeout=_timeout,
                )
            except asyncio.TimeoutError:
                from ira.config import get_settings
                _timeout = get_settings().app.pipeline_timeout
                logger.error(
                    "Pipeline timed out after %ds for sender=%s",
                    _timeout, sender_id,
                )
                return (
                    f"I'm sorry, the request timed out after {_timeout} seconds. "
                    "Please try a simpler question or ask about one topic at a time.",
                    ["timeout"],
                )

    async def _process_request_inner(
        self,
        raw_input: str,
        channel: str,
        sender_id: str,
        metadata: dict[str, Any] | None = None,
        on_progress: Any | None = None,
    ) -> tuple[str, list[str]]:
        """Run the full 11-step pipeline and return ``(shaped_response, agents_used)``."""
        t0 = time.monotonic()
        t_last = t0
        run_stages: dict[str, float] = {}
        meta = metadata or {}
        trace: dict[str, Any] = {"channel": channel, "sender_id": sender_id}

        def _record_stage(name: str) -> None:
            nonlocal t_last
            run_stages[name] = round(time.monotonic() - t_last, 3)
            t_last = time.monotonic()

        def _push_timings() -> None:
            if run_stages:
                self._stage_timings.append({"stages": dict(run_stages), "timestamp": time.time()})

        # ── 0. CLARIFICATION RESUME ───────────────────────────────────
        pending = await self._pop_clarification(sender_id)
        if pending is not None:
            pass  # handled below

        # ── 0.5 DEDUPLICATION ─────────────────────────────────────────
        import hashlib

        _now = time.monotonic()
        _fingerprint = hashlib.sha256(f"{sender_id}:{raw_input}".encode()).hexdigest()[:16]
        _redis_dedup_key = f"{sender_id}:{_fingerprint}"

        if pending is None and self._redis is not None and self._redis.available:
            _redis_hit = await self._redis.dedup_check(_redis_dedup_key)
            if _redis_hit is not None:
                logger.info("DEDUP | Redis cache hit for %s", sender_id)
                return _redis_hit, []

        async with self._state_lock:
            self._recent_messages = {
                k: v for k, v in self._recent_messages.items()
                if _now - v[1] < 300
            }
            if pending is None and _fingerprint in self._recent_messages:
                logger.info("DEDUP | returning cached response for %s", sender_id)
                cached_resp = self._recent_messages[_fingerprint][0]
                return cached_resp, []

        if pending is not None:
            agent = self._pantheon.get_agent(pending["agent_name"])
            if agent is not None:
                followup_ctx = {
                    "original_query": pending["original_query"],
                    "clarification_answer": raw_input,
                    "channel": channel,
                }
                try:
                    raw_response = await agent.handle(
                        pending["original_query"], followup_ctx,
                    )
                    logger.info("CLARIFY-RESUME | agent=%s", pending["agent_name"])
                    shaped = await self._voice.shape_response(
                        raw_response, channel,
                    )
                    return shaped, [pending["agent_name"]]
                except (ToolExecutionError, Exception):
                    logger.exception("Clarification resume failed")

        # ── 0.9 RESET BOREDOM (living system: any user interaction resets idle) ──
        if self._endocrine is not None:
            try:
                self._endocrine.reset_boredom()
            except Exception:
                logger.debug("reset_boredom failed", exc_info=True)

        # ── 1. PERCEIVE ───────────────────────────────────────────────
        if on_progress:
            await on_progress({"type": "perceiving"})

        from ira.systems.sensory import PerceptionEvent

        event = PerceptionEvent(
            channel=Channel(channel.upper() if isinstance(channel, str) else channel),
            raw_input=raw_input,
            sender_id=sender_id,
            sender_name=meta.get("sender_name"),
            metadata=meta,
        )
        perception = await self._sensory.perceive(event)
        contact_info = perception["resolved_contact"]
        contact_email = contact_info["email"]
        trace["contact"] = contact_email
        _record_stage("perceive")
        logger.info("PERCEIVE | %s | %s", channel, contact_email)

        # ── 2. REMEMBER ──────────────────────────────────────────────
        if on_progress:
            await on_progress({"type": "remembering"})

        history = await self._conversation.get_history(
            contact_email, channel, limit=20,
        )

        resolved_input = raw_input
        if history:
            try:
                resolved_input = await self._conversation.resolve_coreferences(
                    raw_input, history,
                )
            except (DatabaseError, Exception):
                logger.exception("Coreference resolution failed")

        # Summarize older history for context enrichment (keep recent 5 verbatim)
        _history_summary = ""
        try:
            _recent_msgs, _history_summary = await self._conversation.get_summarized_history(
                contact_email, channel, recent_limit=5, full_limit=20,
            )
        except (DatabaseError, Exception):
            logger.debug("Summarized history not available", exc_info=True)

        cross_channel_history: list[dict[str, Any]] = []
        if self._unified_ctx is not None:
            try:
                cross_channel_history = self._unified_ctx.recent_history(
                    contact_email, limit=10,
                )
            except (DatabaseError, Exception):
                logger.exception("UnifiedContextManager lookup failed")

        # Still fetch active_goal for the LEARN step (slot extraction)
        active_goal = None
        if self._goals is not None:
            try:
                active_goal = await self._goals.get_active_goal(contact_email)
            except (DatabaseError, Exception):
                logger.exception("GoalManager lookup failed")

        _record_stage("remember")
        logger.info(
            "REMEMBER | history=%d msgs | cross_channel=%d | goal=%s | summary=%s",
            len(history),
            len(cross_channel_history),
            active_goal.goal_type.value if active_goal else "none",
            "yes" if _history_summary else "no",
        )

        # ── 2.5 FAST PATH ────────────────────────────────────────────
        from ira.brain.fast_path import classify as _fp_classify, generate as _fp_generate

        _fast_result = _fp_classify(resolved_input)
        if _fast_result.matched:
            if on_progress:
                await on_progress({"type": "fast_path", "category": _fast_result.category.value if _fast_result.category else None})
            _fp_response = _fast_result.response
            if _fp_response is None:
                _fp_response = await _fp_generate(resolved_input, _fast_result.category)
            logger.info("FAST PATH | category=%s", _fast_result.category)

            if on_progress:
                await on_progress({"type": "shaping"})
            shaped = await self._voice.shape_response(_fp_response, channel)

            _record_stage("route")
            _record_stage("shape")
            await self._learn(
                contact_email=contact_email,
                channel=channel,
                raw_input=raw_input,
                raw_response=_fp_response,
                route_method="fast_path",
                agents_used=["fast_path"],
                active_goal=active_goal,
                resolved_input=resolved_input,
            )
            _record_stage("learn")
            _push_timings()
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info("RETURN (fast) | %s | %.0fms", contact_email, elapsed_ms)
            self._recent_messages[_fingerprint] = (shaped, _now)
            if self._redis is not None and self._redis.available:
                await self._redis.dedup_store(_redis_dedup_key, shaped, ttl_seconds=300)
            return shaped, ["fast_path"]

        # ── 2.7 SPHINX GATE ──────────────────────────────────────────
        _SPHINX_TIMEOUT = 15
        try:
            sphinx = self._pantheon.get_agent("sphinx")
            if sphinx is not None:
                if on_progress:
                    await on_progress({"type": "sphinx_checking"})
                _sphinx_verdict = await asyncio.wait_for(
                    sphinx.handle(resolved_input, {"channel": channel, "sender_id": sender_id}),
                    timeout=_SPHINX_TIMEOUT,
                )
                _CLARIFY_TAG = "[CLARIFY]"
                _CLEAR_TAG = "[CLEAR]"
                if _sphinx_verdict.startswith(_CLARIFY_TAG):
                    clarification_q = _sphinx_verdict[len(_CLARIFY_TAG):].strip()
                    if on_progress:
                        await on_progress({"type": "sphinx_clarifying", "questions": clarification_q[:300]})
                    clarification_data = {
                        "agent_name": "sphinx",
                        "original_query": resolved_input,
                        "clarification_question": clarification_q,
                    }
                    async with self._state_lock:
                        self._pending_clarifications[sender_id] = clarification_data
                    await self._persist_clarification(sender_id, clarification_data)
                    logger.info("SPHINX CLARIFY | stored pending for %s", contact_email)
                    shaped = await self._voice.shape_response(clarification_q, channel)
                    _record_stage("route")
                    _push_timings()
                    return shaped, ["sphinx"]
                elif _sphinx_verdict.startswith(_CLEAR_TAG):
                    logger.info("SPHINX CLEAR | query is actionable")
        except asyncio.TimeoutError:
            logger.warning("Sphinx gate timed out after %ds — proceeding", _SPHINX_TIMEOUT)
        except (IraError, Exception):
            logger.debug("Sphinx gate failed (non-critical)", exc_info=True)

        # ── 3. ROUTE (Fast) ──────────────────────────────────────────
        if on_progress:
            await on_progress({"type": "routing", "method": "checking"})

        routing = self._router.route(resolved_input)
        route_method: str | None = None
        agent_names: list[str] = []

        if routing is not None:
            route_method = "deterministic"
            agent_names = routing["required_agents"]
            logger.info("ROUTE FAST | intent=%s -> %s", routing["intent"], agent_names)

        # ── 3.5 TRUTH HINTS ──────────────────────────────────────────
        truth_hint_response: str | None = None
        if route_method is None:
            try:
                from ira.brain.truth_hints import TruthHintsEngine
                engine = TruthHintsEngine()
                await engine._load()
                if not engine.is_complex_query(resolved_input):
                    hint = engine.match(resolved_input)
                    if hint is not None:
                        truth_hint_response = hint["answer"]
                        route_method = "truth_hint"
                        agent_names = []
                        logger.info("TRUTH HINT | matched: %s", hint.get("patterns", ["?"])[0][:60])
            except (IraError, Exception):
                logger.debug("Truth hints check failed (non-critical)")

        # ── 4. ROUTE (Procedure) ─────────────────────────────────────
        procedure = None
        if route_method is None and self._procedural is not None:
            try:
                procedure = await self._procedural.find_procedure(resolved_input)
            except (DatabaseError, Exception):
                logger.exception("ProceduralMemory lookup failed")

            if procedure is not None:
                route_method = "procedural"
                agent_names = procedure.steps
                logger.info(
                    "ROUTE PROCEDURE | pattern=%s (used %dx)",
                    procedure.trigger_pattern,
                    procedure.times_used,
                )

        # ── 5. ROUTE (LLM) ──────────────────────────────────────────
        if route_method is None:
            route_method = "llm"
            logger.info("ROUTE LLM | delegating to Athena")
        _record_stage("route")

        # ── 5.1 RESOLVE EMAIL SCOPE ───────────────────────────────
        email_scope = self._resolve_email_scope(resolved_input)
        logger.info("EMAIL SCOPE | %s", email_scope)

        # ── 5.5 ENRICH CONTEXT ─────────────────────────────────────
        if on_progress:
            await on_progress({"type": "enriching"})

        enrichment_parts: list[str] = []

        try:
            if self._adaptive_style is not None:
                style_tracker = self._adaptive_style
            else:
                from ira.brain.adaptive_style import AdaptiveStyleTracker
                style_tracker = AdaptiveStyleTracker()
                await style_tracker._load()
            await style_tracker.update_profile(contact_email, raw_input)
            style_prompt = style_tracker.get_style_prompt(contact_email)
            if style_prompt:
                enrichment_parts.append(style_prompt)
        except (IraError, Exception):
            logger.debug("AdaptiveStyle not available")

        try:
            if self._realtime_observer is not None:
                observer = self._realtime_observer
            else:
                from ira.brain.realtime_observer import RealTimeObserver
                observer = RealTimeObserver()
                await observer._load()
            learnings_prompt = observer.format_for_prompt(contact_email)
            if learnings_prompt:
                enrichment_parts.append(learnings_prompt)
        except (IraError, Exception):
            logger.debug("RealTimeObserver not available")

        if self._endocrine is not None:
            try:
                status = self._endocrine.get_status()
                enrichment_parts.append(
                    f"System state: confidence={status.get('confidence', 0.5):.2f} "
                    f"energy={status.get('energy', 0.5):.2f}"
                )
            except (IraError, Exception):
                logger.debug("Endocrine status not available", exc_info=True)

        try:
            if self._power_level_tracker is not None:
                tracker = self._power_level_tracker
            else:
                from ira.brain.power_levels import PowerLevelTracker
                tracker = PowerLevelTracker()
                await tracker._load()
            top = tracker.get_leaderboard()[:3]
            if top:
                enrichment_parts.append(
                    "Top agents: " + ", ".join(
                        f"{a['agent']}({a['tier']})" for a in top
                    )
                )
        except (IraError, Exception):
            logger.debug("PowerLevelTracker not available", exc_info=True)

        try:
            chiron = self._pantheon.get_agent("chiron")
            if chiron is not None and hasattr(chiron, "get_sales_guidance"):
                guidance = await chiron.get_sales_guidance()
                if guidance and len(guidance) > 20:
                    enrichment_parts.append(f"Sales coaching:\n{guidance[:500]}")
        except (ToolExecutionError, Exception):
            logger.debug("Chiron sales guidance not available", exc_info=True)

        if _history_summary:
            enrichment_parts.append(f"Earlier conversation summary:\n{_history_summary}")

        if self._episodic is not None:
            try:
                episodes = await self._episodic.surface_relevant_episodes(
                    resolved_input, contact_email,
                )
                if episodes:
                    ep_text = "\n".join(
                        f"- {e.get('narrative', '')[:200]}" for e in episodes[:3]
                    )
                    enrichment_parts.append(f"Relevant past interactions:\n{ep_text}")
            except (IraError, Exception):
                logger.debug("Episodic memory enrichment not available", exc_info=True)
        _record_stage("enrich")

        # ── 6. EXECUTE ───────────────────────────────────────────────
        # Pass perception and enrichment for prompt context, plus live
        # service references so agents can query memory dynamically
        # through their ReAct tools instead of relying on static snapshots.
        services: dict[str, Any] = {
            "_delegation_depth": 0,
            "conversation_memory": self._conversation,
            "relationship_memory": self._relationship,
            "goal_manager": self._goals,
            "procedural_memory": self._procedural,
            "crm": self._crm,
            "endocrine": self._endocrine,
        }
        if self._tool_stats_tracker is not None:
            services["tool_stats_tracker"] = self._tool_stats_tracker
        ctx = PipelineContextModel(
            perception=perception,
            channel=channel,
            services=services,
            enrichment="\n\n".join(enrichment_parts) if enrichment_parts else "",
        )
        context: dict[str, Any] = ctx.model_dump()
        context["email_scope"] = email_scope
        if self._agent_journal is not None:
            context["_agent_journal"] = self._agent_journal

        raw_response: str
        agents_used: list[str]

        if truth_hint_response is not None:
            raw_response = truth_hint_response
            agents_used = ["truth_hints"]
        elif route_method in ("deterministic", "procedural"):
            raw_response, agents_used = await self._execute_routed(
                agent_names, resolved_input, context, on_progress,
            )
        else:
            raw_response = await self._pantheon.process(
                resolved_input, context, on_progress=on_progress,
            )
            agents_used = ["athena"]

        _record_stage("execute")
        trace["route"] = route_method
        trace["agents"] = agents_used
        logger.info("EXECUTE | route=%s agents=%s", route_method, agents_used)

        # ── 6.1a COMPLIANCE CHECK (Aletheia) ─────────────────────────
        aletheia = self._pantheon.get_agent("aletheia")
        if aletheia is not None:
            try:
                provenance = await aletheia.check_provenance(raw_response)
                if provenance.get("unverifiable"):
                    _unverified = provenance["unverifiable"]
                    _note = (
                        "\n\n> **Provenance note:** "
                        + f"{len(_unverified)} claim(s) could not be traced to a source: "
                        + ", ".join(_unverified[:3])
                        + ("..." if len(_unverified) > 3 else "")
                        + "."
                    )
                    raw_response += _note
                    if "aletheia" not in agents_used:
                        agents_used.append("aletheia")
                    logger.info("ALETHEIA | verdict=%s unverifiable=%d", provenance["verdict"], len(_unverified))
            except Exception:
                logger.exception("Aletheia compliance check failed")
        _record_stage("compliance")

        # ── 6.1b DLP CHECK (Aegis) ───────────────────────────────────
        aegis = self._pantheon.get_agent("aegis")
        if aegis is not None:
            try:
                dlp_result = await aegis.check_content(raw_response)
                if dlp_result["verdict"] == "BLOCK":
                    raw_response = (
                        "I can't share this response as it contains confidential "
                        "business data. Please rephrase your request."
                    )
                    logger.warning("AEGIS | BLOCK — response replaced")
                elif dlp_result["verdict"] == "REVIEW_NEEDED":
                    raw_response += (
                        "\n\n> **Content note:** This response may contain "
                        "sensitive data. Review before sharing externally."
                    )
                    logger.info("AEGIS | REVIEW_NEEDED — caveat appended")
                if "aegis" not in agents_used:
                    agents_used.append("aegis")
            except Exception:
                logger.exception("Aegis DLP check failed")
        _record_stage("dlp")

        # ── 6.2 CORRECTION CHECK (Mnemon) ────────────────────────────
        mnemon = self._pantheon.get_agent("mnemon")
        if mnemon is not None:
            try:
                corrected = await mnemon.check_and_correct(raw_response)
                if corrected != raw_response:
                    raw_response = corrected
                    if "mnemon" not in agents_used:
                        agents_used.append("mnemon")
                    logger.info("MNEMON | corrections applied to response")
            except Exception:
                logger.exception("Mnemon correction check failed")

        # ── 6.3 GAP RESOLUTION ───────────────────────────────────────
        gapper = self._pantheon.get_agent("gapper")
        if gapper is not None:
            try:
                from ira.agents.gapper import detect_gaps
                gaps = detect_gaps(raw_response)
                if gaps:
                    if on_progress:
                        await on_progress({"type": "gap_resolving", "gaps": len(gaps)})
                    logger.info("GAP RESOLVE | %d gaps detected, invoking Gapper", len(gaps))
                    resolved = await gapper.resolve_gaps(raw_response, resolved_input)
                    if resolved and resolved != raw_response:
                        raw_response = resolved
                        agents_used.append("gapper")
            except Exception:
                logger.exception("Gapper resolution failed, continuing with original response")

        # ── 6.4 FAITHFULNESS GATE ─────────────────────────────────────
        if route_method not in ("truth_hint", "fast_path"):
            try:
                from ira.brain.guardrails import check_faithfulness
                from ira.config import get_settings as _get_settings

                _app_cfg = _get_settings().app
                retriever = self._pantheon.retriever
                _faith_kb = await retriever.search(resolved_input, limit=5)
                _faith_docs = [
                    r.get("content", "") for r in _faith_kb if r.get("content")
                ]
                if _faith_docs:
                    if on_progress:
                        await on_progress({"type": "faithfulness_check"})
                    _faith_result = await check_faithfulness(raw_response, _faith_docs)
                    trace["faithfulness"] = _faith_result.get("score", 1.0)
                    _faith_score = _faith_result.get("score", 1.0)

                    _agents_did_real_work = (
                        len(agents_used) > 1
                        or (agents_used and agents_used[0] not in ("athena", "timeout", "truth_hints", "fast_path"))
                    )
                    _response_is_substantive = len(raw_response) > 200

                    if _faith_score < _app_cfg.faithfulness_hard_threshold and not (
                        _agents_did_real_work and _response_is_substantive
                    ):
                        raw_response = (
                            "I can't provide a reliable answer from the current evidence. "
                            "Please narrow the request or provide additional source documents."
                        )
                        trace["faithfulness_blocked"] = True
                        logger.warning(
                            "FAITHFULNESS | score=%.2f < hard threshold %.2f — response blocked",
                            _faith_score, _app_cfg.faithfulness_hard_threshold,
                        )
                    elif _faith_score < _app_cfg.faithfulness_threshold or (
                        _faith_score < _app_cfg.faithfulness_hard_threshold
                        and _agents_did_real_work
                    ):
                        _caveat = (
                            "\n\n> Note: Some claims could not be fully verified "
                            "against our documentation. Please cross-check "
                            "critical details."
                        )
                        raw_response += _caveat
                        logger.info(
                            "FAITHFULNESS | score=%.2f < %.2f — caveat appended",
                            _faith_score, _app_cfg.faithfulness_threshold,
                        )
            except (LLMError, Exception):
                logger.warning("Faithfulness gate failed — continuing with unverified response", exc_info=True)
        _record_stage("faithfulness")

        # ── 6.4b GUARDRAILS (LLM-routed responses) ───────────────────
        if route_method == "llm":
            try:
                from ira.brain.guardrails import (
                    check_competitor_mentions,
                    check_confidentiality,
                )
                from ira.config import get_settings as _get_settings_guardrails

                _guardrails_fail_closed = _get_settings_guardrails().app.guardrails_fail_closed

                _guard_conf, _guard_comp = await asyncio.gather(
                    check_confidentiality(raw_response, "external"),
                    check_competitor_mentions(raw_response),
                    return_exceptions=True,
                )
                _guardrail_results: dict[str, Any] = {}
                _guardrail_violation = False

                if isinstance(_guard_conf, Exception):
                    logger.warning("GUARDRAILS | confidentiality check failed", exc_info=True)
                    if _guardrails_fail_closed:
                        _guardrail_results["confidentiality_check_error"] = str(_guard_conf)
                        _guardrail_violation = True
                elif isinstance(_guard_conf, dict) and not _guard_conf.get("safe", True):
                    _guardrail_results["confidentiality"] = _guard_conf
                    logger.warning(
                        "GUARDRAILS | confidential data detected: %s",
                        _guard_conf.get("leaked_categories"),
                    )
                    _guardrail_violation = True

                if isinstance(_guard_comp, Exception):
                    logger.warning("GUARDRAILS | competitor check failed", exc_info=True)
                    if _guardrails_fail_closed:
                        _guardrail_results["competitor_check_error"] = str(_guard_comp)
                        _guardrail_violation = True
                elif isinstance(_guard_comp, dict) and not _guard_comp.get("clean", True):
                    _guardrail_results["competitors"] = _guard_comp
                    logger.warning(
                        "GUARDRAILS | competitor mentions: %s",
                        [m["competitor"] for m in _guard_comp.get("mentions", [])],
                    )
                    _guardrail_violation = True

                if _guardrail_results:
                    trace["guardrails"] = _guardrail_results

                if _guardrails_fail_closed and _guardrail_violation:
                    raw_response = (
                        "I can't provide that response safely. "
                        "Please rephrase your request for a policy-compliant summary."
                    )
                    logger.warning(
                        "GUARDRAILS | fail-closed triggered; response replaced with safe fallback",
                    )
            except (IraError, Exception):
                logger.warning("Guardrails checks failed (non-critical)", exc_info=True)

        # ── 6.5 CLARIFICATION CHECK ──────────────────────────────────
        _CLARIFY_PREFIX = "[CLARIFY]"
        if raw_response.startswith(_CLARIFY_PREFIX):
            clarification_q = raw_response[len(_CLARIFY_PREFIX):].strip()
            clarification_data = {
                "agent_name": agents_used[0] if agents_used else "athena",
                "original_query": resolved_input,
                "clarification_question": clarification_q,
            }
            async with self._state_lock:
                self._pending_clarifications[sender_id] = clarification_data
            await self._persist_clarification(sender_id, clarification_data)
            logger.info("CLARIFY | stored pending for %s (sender=%s)", contact_email, sender_id)
            shaped = await self._voice.shape_response(clarification_q, channel)
            _push_timings()
            return shaped, agents_used

        # ── 7. ASSESS ────────────────────────────────────────────────
        if on_progress:
            await on_progress({"type": "assessing"})

        confidence_prefix = ""
        if self._metacognition is not None:
            try:
                retriever = self._pantheon.retriever
                kb_results = await retriever.search(resolved_input, limit=5)
                assessment = await self._metacognition.assess_knowledge(
                    resolved_input, kb_results,
                )
                confidence_prefix = self._metacognition.generate_confidence_prefix(
                    assessment["state"], assessment["confidence"],
                )
                trace["confidence"] = assessment["confidence"]

                if assessment.get("gaps"):
                    await self._metacognition.log_knowledge_gap(
                        resolved_input,
                        assessment["state"],
                        assessment["gaps"],
                    )

                # ── 7.1 CONFIDENCE FLOOR ──────────────────────────────
                from ira.config import get_settings as _get_settings_assess
                from ira.data.models import KnowledgeState

                _assess_cfg = _get_settings_assess().app
                _state = assessment["state"]
                _conf = assessment["confidence"]
                _is_unknown = _state == KnowledgeState.UNKNOWN
                _is_low_uncertain = (
                    _state == KnowledgeState.UNCERTAIN
                    and _conf < _assess_cfg.confidence_floor
                )

                _agents_did_work = len(agents_used) > 1 or (
                    agents_used and agents_used[0] not in ("athena", "timeout")
                )
                _response_has_substance = len(raw_response) > 200

                if (_is_unknown or _is_low_uncertain) and not (
                    _agents_did_work and _response_has_substance
                ):
                    raw_response = (
                        "I don't have reliable information to answer this "
                        "question accurately. I'd recommend checking with "
                        "the relevant team or documentation directly."
                    )
                    logger.info(
                        "CONFIDENCE FLOOR | state=%s confidence=%.2f — "
                        "replaced response with honest 'I don't know'",
                        _state, _conf,
                    )
                elif (_is_unknown or _is_low_uncertain) and _agents_did_work:
                    raw_response = confidence_prefix + raw_response
                    logger.info(
                        "CONFIDENCE FLOOR | state=%s confidence=%.2f — "
                        "agents provided substantive response, prefixing "
                        "instead of replacing",
                        _state, _conf,
                    )
                elif _state == KnowledgeState.CONFLICTING:
                    _conflicts = assessment.get("conflicts", [])
                    if _conflicts:
                        _conflict_lines = "\n".join(
                            f"- {c}" for c in _conflicts[:5]
                        )
                        confidence_prefix += (
                            f"Specific conflicts found:\n{_conflict_lines}\n\n"
                        )
            except (LLMError, Exception):
                logger.exception("Metacognition assessment failed")
        _record_stage("assess")

        # ── 8. REFLECT ───────────────────────────────────────────────
        if on_progress:
            await on_progress({"type": "reflecting"})

        reflection_text = ""
        if self._inner_voice is not None:
            try:
                reflection = await self._inner_voice.reflect(
                    context=f"User ({contact_email}) on {channel}: {raw_input}",
                    trigger=raw_response[:500],
                )
                if reflection.get("should_surface") and reflection.get("content"):
                    reflection_text = f"\n\n_{reflection['content']}_"
            except (LLMError, Exception):
                logger.exception("InnerVoice reflection failed")

        # ── 8.5 SOURCE LIMITATION NOTE ────────────────────────────────
        _source_limitations: list[str] = []
        for _au in agents_used:
            _agent_resp = raw_response
            if f"Agent '{_au}' timed out" in _agent_resp:
                _source_limitations.append(f"{_au} timed out")
            if f"Agent '{_au}' encountered an error" in _agent_resp:
                _source_limitations.append(f"{_au} failed")
        if "timeout" in agents_used:
            _source_limitations.append("pipeline timed out")
        if _source_limitations:
            _limitation_note = (
                "\n\n> **Note:** " + "; ".join(_source_limitations) + ". "
                "This answer may be based on partial data."
            )
            raw_response += _limitation_note
            logger.info("SOURCE LIMITATION | %s", _source_limitations)

        # ── 9. SHAPE ─────────────────────────────────────────────────
        if on_progress:
            await on_progress({"type": "shaping"})

        full_response = confidence_prefix + raw_response + reflection_text

        recipient = Contact(
            name=contact_info.get("name", ""),
            email=contact_email,
            company=contact_info.get("company"),
            region=contact_info.get("region"),
            source="pipeline",
        )

        modifiers = {}
        if self._endocrine is not None:
            try:
                modifiers = self._endocrine.get_behavioral_modifiers()
            except (IraError, Exception):
                logger.exception("Endocrine modifiers failed")

        shaped = await self._voice.shape_response(
            full_response,
            channel,
            recipient=recipient,
            behavioral_modifiers=modifiers,
        )

        _record_stage("shape")
        logger.info("SHAPE | channel=%s len=%d", channel, len(shaped))

        # ── 9.5 LOG SESSION (Graphe) ─────────────────────────────────
        graphe = self._pantheon.get_agent("graphe")
        if graphe is not None:
            try:
                await graphe.log_turn(
                    query=raw_input,
                    agents_used=agents_used,
                    response_summary=raw_response[:300],
                )
            except Exception:
                logger.debug("Graphe session logging failed", exc_info=True)

        # ── 9.6 STABILITY SCORING (Metis) ────────────────────────────
        metis = self._pantheon.get_agent("metis")
        _metis_note = ""
        if metis is not None:
            try:
                metis_result = await metis.score_and_track(agents_used, raw_response)
                if metis_result.get("should_announce_stable"):
                    _metis_note = (
                        f"\n\n---\n**Metis (Stability Monitor):** I think we are stable now "
                        f"at max_rounds={metis_result['max_rounds']} "
                        f"(rolling avg: {metis_result['rolling_avg']}/100). Confirm?"
                    )
                elif metis_result.get("should_report"):
                    _metis_note = (
                        f"\n\n---\n*Stability score: {metis_result['score']}/100 "
                        f"(avg: {metis_result['rolling_avg']}/100, "
                        f"max_rounds: {metis_result['max_rounds']})*"
                    )
            except Exception:
                logger.debug("Metis scoring failed", exc_info=True)
        if _metis_note:
            shaped += _metis_note

        # ── 10. LEARN (background) ───────────────────────────────────
        # Run learning (Sophia, RealTimeObserver, etc.) in background so we return
        # the response immediately; avoids timeout when using CLI/Cursor.
        async def _learn_then_record() -> None:
            await self._learn(
                contact_email=contact_email,
                channel=channel,
                raw_input=raw_input,
                raw_response=raw_response,
                route_method=route_method,
                agents_used=agents_used,
                active_goal=active_goal,
                resolved_input=resolved_input,
            )
            _record_stage("learn")
            _push_timings()

        _learn_task = asyncio.create_task(_learn_then_record())
        _learn_task.add_done_callback(
            lambda t: t.exception() and logger.warning("LEARN background task failed: %s", t.exception())
        )

        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "RETURN | %s | %.0fms | route=%s agents=%s",
            contact_email,
            elapsed_ms,
            route_method,
            agents_used,
        )

        # ── 11. RETURN ───────────────────────────────────────────────
        self._recent_messages[_fingerprint] = (shaped, _now)
        if self._redis is not None and self._redis.available:
            await self._redis.dedup_store(_redis_dedup_key, shaped, ttl_seconds=300)
        return shaped, agents_used

    # ── Email scope resolver ─────────────────────────────────────────────

    _LIVE_EMAIL_PATTERNS = re.compile(
        r"(latest|recent|today|yesterday|new|unread|inbox|just sent|this morning|"
        r"last\s+(hour|day|week)|what did .+ (say|send|write|reply))",
        re.IGNORECASE,
    )
    _EMAIL_PATTERNS = re.compile(
        r"(email|mail|thread|inbox|gmail|message from|correspondence|"
        r"draft|reply|follow.?up email|send .+ email)",
        re.IGNORECASE,
    )

    def _resolve_email_scope(self, query: str) -> str:
        """Classify the query's email data scope: live_email, imported_email, both, or no_email."""
        has_email_mention = bool(self._EMAIL_PATTERNS.search(query))
        needs_live = bool(self._LIVE_EMAIL_PATTERNS.search(query))

        if not has_email_mention:
            return "no_email"
        if needs_live and has_email_mention:
            return "both"
        if needs_live:
            return "live_email"
        return "imported_email"

    # ── Execution helpers ─────────────────────────────────────────────────

    _AGENT_TIMEOUT = 60

    async def _execute_routed(
        self,
        agent_names: list[str],
        query: str,
        context: dict[str, Any],
        on_progress: Any | None = None,
    ) -> tuple[str, list[str]]:
        """Execute one or more agents sequentially, returning (response, names_used)."""
        used: list[str] = []
        responses: dict[str, str] = {}

        for name in agent_names:
            agent = self._pantheon.get_agent(name)
            if agent is None:
                logger.warning("Agent '%s' not found — skipping", name)
                continue
            if on_progress:
                await on_progress({"type": "agent_started", "agent": name, "role": getattr(agent, "role", "")})
            try:
                resp = await asyncio.wait_for(
                    agent.handle(query, context),
                    timeout=self._AGENT_TIMEOUT,
                )
                responses[name] = resp
                used.append(name)
            except asyncio.TimeoutError:
                logger.warning("Agent '%s' timed out after %ds", name, self._AGENT_TIMEOUT)
                responses[name] = f"(Agent '{name}' timed out after {self._AGENT_TIMEOUT}s)"
                used.append(name)
            except (ToolExecutionError, Exception):
                logger.exception("Agent '%s' failed during execution", name)
                responses[name] = f"(Agent '{name}' encountered an error)"
                used.append(name)
            if on_progress:
                await on_progress({"type": "agent_done", "agent": name, "preview": responses[name][:200]})

        if not responses:
            return await self._pantheon.process(query, context, on_progress=on_progress), ["athena"]

        if len(responses) == 1:
            return next(iter(responses.values())), used

        athena = self._pantheon.get_agent("athena")
        if athena is not None:
            if on_progress:
                await on_progress({"type": "synthesizing", "agent": "athena"})
            synthesised = await athena.handle(
                query, {"agent_responses": responses},
            )
            return synthesised, used + ["athena"]

        return "\n\n".join(responses.values()), used

    # ── Learning step ─────────────────────────────────────────────────────

    async def _learn(
        self,
        *,
        contact_email: str,
        channel: str,
        raw_input: str,
        raw_response: str,
        route_method: str,
        agents_used: list[str],
        active_goal: Any | None,
        resolved_input: str,
    ) -> None:
        """Step 10: record the interaction across all memory and tracking systems."""

        # Conversation memory
        try:
            await self._conversation.add_message(contact_email, channel, "user", raw_input)
            await self._conversation.add_message(contact_email, channel, "assistant", raw_response)
        except (DatabaseError, Exception):
            logger.exception("ConversationMemory recording failed")

        # Durable fact extraction into long-term semantic memory
        if self._long_term is not None:
            try:
                from ira.services.llm_client import get_llm_client
                _fact_llm = get_llm_client()
                _facts_raw = await _fact_llm.generate_text(
                    "Extract durable facts from this exchange — preferences, "
                    "decisions, business context about the contact. Return one "
                    "fact per line. Return NONE if no durable facts exist.",
                    f"Contact: {contact_email}\nUser: {raw_input[:500]}\n"
                    f"Assistant: {raw_response[:500]}",
                    name="pipeline.extract_facts",
                )
                if _facts_raw and _facts_raw.strip().upper() != "NONE":
                    for fact_line in _facts_raw.strip().splitlines():
                        fact = fact_line.strip().lstrip("- ")
                        if fact and len(fact) > 10:
                            await self._long_term.store_fact(
                                fact,
                                source=f"conversation:{contact_email}",
                                confidence=0.7,
                            )
                    logger.debug("LEARN | extracted durable facts for %s", contact_email)
            except (LLMError, Exception):
                logger.debug("Fact extraction failed (non-critical)", exc_info=True)

        # CRM interaction log
        if self._crm is not None:
            try:
                contact_record = await self._crm.get_contact_by_email(contact_email)
                if contact_record is not None:
                    await self._crm.create_interaction(
                        contact_id=str(contact_record.id),
                        channel=Channel(channel),
                        direction=Direction.INBOUND,
                        subject=raw_input[:200],
                        content=json.dumps({
                            "query": raw_input,
                            "response_preview": raw_response[:500],
                            "route": route_method,
                            "agents": agents_used,
                        }, default=str),
                    )
            except (DatabaseError, Exception):
                logger.exception("CRM interaction logging failed")

        # Musculoskeletal action tracking
        if self._musculoskeletal is not None:
            try:
                from ira.systems.musculoskeletal import ActionRecord, ActionType

                await self._musculoskeletal.record_action(
                    ActionRecord(
                        action_type=ActionType.RESEARCH_COMPLETED,
                        target=contact_email,
                        details={
                            "channel": channel,
                            "route": route_method,
                            "agents": agents_used,
                            "query_preview": raw_input[:200],
                        },
                    )
                )
            except (IraError, Exception):
                logger.exception("MusculoskeletalSystem recording failed")

        # Goal slot extraction
        if active_goal is not None and self._goals is not None:
            try:
                extracted = await self._goals.extract_slots(active_goal, raw_input)
                if extracted:
                    await self._goals.update_goal(active_goal.id, extracted)
            except (DatabaseError, Exception):
                logger.exception("GoalManager slot update failed")

        # Goal detection for new goals
        if active_goal is None and self._goals is not None:
            try:
                await self._goals.detect_goal(
                    resolved_input,
                    {"contact_id": contact_email, "channel": channel},
                )
            except (DatabaseError, Exception):
                logger.exception("GoalManager detection failed")

        # Procedural learning
        if self._procedural is not None and route_method in ("deterministic", "llm"):
            try:
                await self._procedural.learn_procedure(
                    resolved_input, agents_used,
                )
            except (DatabaseError, Exception):
                logger.exception("ProceduralMemory learning failed")

        # Trigger Sophia for background reflection (fire-and-forget)
        sophia = self._pantheon.get_agent("sophia")
        if sophia is not None:
            try:
                await sophia.handle(
                    f"Reflect on this interaction: {raw_input[:300]}",
                    {"response": raw_response[:300], "route": route_method},
                )
            except (ToolExecutionError, Exception):
                logger.warning("Sophia reflection failed", exc_info=True)

        try:
            from ira.brain.realtime_observer import RealTimeObserver
            observer = RealTimeObserver()
            await observer._load()
            _task = asyncio.create_task(
                observer.observe_turn(raw_input, raw_response, contact_email)
            )
            _task.add_done_callback(
                lambda t: t.exception() and logger.warning(
                    "RealTimeObserver task failed: %s", t.exception()
                )
            )
        except (IraError, Exception):
            logger.warning("RealTimeObserver not available", exc_info=True)

        # Endocrine feedback
        if self._endocrine is not None:
            try:
                self._endocrine.boost("growth_signal", 0.02)
                if route_method == "deterministic":
                    self._endocrine.boost("confidence", 0.01)
            except (IraError, Exception):
                logger.warning("Endocrine update failed", exc_info=True)

        if self._unified_ctx is not None:
            try:
                self._unified_ctx.record_turn(
                    contact_email, channel, raw_input, raw_response,
                )
            except (DatabaseError, Exception):
                logger.exception("UnifiedContextManager recording failed")

        logger.info("LEARN | recorded for %s", contact_email)
