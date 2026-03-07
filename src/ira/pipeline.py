"""Master request-processing pipeline — 11 steps from raw input to shaped response.

Every inbound message, regardless of channel, flows through
:func:`RequestPipeline.process_request`.  The pipeline is intentionally
linear so that each step can be individually logged, timed, and tested.

Steps
-----
1. **PERCEIVE** — SensorySystem resolves identity, emotional state, history.
2. **REMEMBER** — ConversationMemory, RelationshipMemory, GoalManager.
3. **ROUTE (Fast)** — DeterministicRouter for keyword-matched intents.
4. **ROUTE (Procedure)** — ProceduralMemory for learned response patterns.
5. **ROUTE (LLM)** — Athena for open-ended LLM-based routing.
6. **EXECUTE** — Routed agent(s) produce a raw response.
7. **ASSESS** — Metacognition evaluates confidence and adds caveats.
8. **REFLECT** — InnerVoice surfaces optional reflections.
9. **SHAPE** — VoiceSystem formats for channel and recipient.
10. **LEARN** — Record in ConversationMemory, CRM, MusculoskeletalSystem; trigger Sophia.
11. **RETURN** — Final shaped response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from ira.data.models import Channel, Contact, Direction

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

        self._router = pantheon._router
        self._pending_clarifications: dict[str, dict[str, Any]] = {}
        self._recent_messages: dict[str, tuple[str, float]] = {}

    # ── Public entry point ────────────────────────────────────────────────

    async def process_request(
        self,
        raw_input: str,
        channel: str,
        sender_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Run the full 11-step pipeline and return the shaped response."""
        t0 = time.monotonic()
        meta = metadata or {}
        trace: dict[str, Any] = {"channel": channel, "sender_id": sender_id}

        # ── 0. CLARIFICATION RESUME ───────────────────────────────────
        pending = self._pending_clarifications.pop(sender_id, None)
        if pending is not None:
            pass  # handled below

        # ── 0.5 DEDUPLICATION ─────────────────────────────────────────
        import hashlib

        _now = time.monotonic()
        _fingerprint = hashlib.sha256(f"{sender_id}:{raw_input}".encode()).hexdigest()[:16]
        self._recent_messages = {
            k: v for k, v in self._recent_messages.items()
            if _now - v[1] < 300
        }
        if pending is None and _fingerprint in self._recent_messages:
            logger.info("DEDUP | returning cached response for %s", sender_id)
            return self._recent_messages[_fingerprint][0]

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
                    return shaped
                except Exception:
                    logger.exception("Clarification resume failed")

        # ── 1. PERCEIVE ───────────────────────────────────────────────
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
        logger.info("PERCEIVE | %s | %s", channel, contact_email)

        # ── 2. REMEMBER ──────────────────────────────────────────────
        # Fetch minimal history for coreference resolution and the LEARN
        # step.  Agents query memory dynamically via their injected
        # services and ReAct tools — we no longer pre-fetch relationship
        # or goal snapshots for the agent context.
        history = await self._conversation.get_history(
            contact_email, channel, limit=20,
        )

        resolved_input = raw_input
        if history:
            try:
                resolved_input = await self._conversation.resolve_coreferences(
                    raw_input, history,
                )
            except Exception:
                logger.exception("Coreference resolution failed")

        cross_channel_history: list[dict[str, Any]] = []
        if self._unified_ctx is not None:
            try:
                cross_channel_history = self._unified_ctx.recent_history(
                    contact_email, limit=10,
                )
            except Exception:
                logger.exception("UnifiedContextManager lookup failed")

        # Still fetch active_goal for the LEARN step (slot extraction)
        active_goal = None
        if self._goals is not None:
            try:
                active_goal = await self._goals.get_active_goal(contact_email)
            except Exception:
                logger.exception("GoalManager lookup failed")

        logger.info(
            "REMEMBER | history=%d msgs | cross_channel=%d | goal=%s",
            len(history),
            len(cross_channel_history),
            active_goal.goal_type.value if active_goal else "none",
        )

        # ── 3. ROUTE (Fast) ──────────────────────────────────────────
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
            except Exception:
                logger.debug("Truth hints check failed (non-critical)")

        # ── 4. ROUTE (Procedure) ─────────────────────────────────────
        procedure = None
        if route_method is None and self._procedural is not None:
            try:
                procedure = await self._procedural.find_procedure(resolved_input)
            except Exception:
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

        # ── 5.5 ENRICH CONTEXT ─────────────────────────────────────
        enrichment_parts: list[str] = []

        try:
            from ira.brain.adaptive_style import AdaptiveStyleTracker
            style_tracker = AdaptiveStyleTracker()
            await style_tracker._load()
            await style_tracker.update_profile(contact_email, raw_input)
            style_prompt = style_tracker.get_style_prompt(contact_email)
            if style_prompt:
                enrichment_parts.append(style_prompt)
        except Exception:
            logger.debug("AdaptiveStyle not available")

        try:
            from ira.brain.realtime_observer import RealTimeObserver
            observer = RealTimeObserver()
            await observer._load()
            learnings_prompt = observer.format_for_prompt(contact_email)
            if learnings_prompt:
                enrichment_parts.append(learnings_prompt)
        except Exception:
            logger.debug("RealTimeObserver not available")

        if self._endocrine is not None:
            try:
                status = self._endocrine.get_status()
                enrichment_parts.append(
                    f"System state: confidence={status.get('confidence', 0.5):.2f} "
                    f"energy={status.get('energy', 0.5):.2f}"
                )
            except Exception:
                pass

        try:
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
        except Exception:
            pass

        try:
            from ira.agents.chiron import Chiron
            chiron = self._pantheon.get_agent("chiron")
            if chiron is not None and hasattr(chiron, "get_sales_guidance"):
                guidance = await chiron.get_sales_guidance()
                if guidance and len(guidance) > 20:
                    enrichment_parts.append(f"Sales coaching:\n{guidance[:500]}")
        except Exception:
            pass

        # ── 6. EXECUTE ───────────────────────────────────────────────
        # Pass perception and enrichment for prompt context, plus live
        # service references so agents can query memory dynamically
        # through their ReAct tools instead of relying on static snapshots.
        context: dict[str, Any] = {
            "perception": perception,
            "channel": channel,
            "services": {
                "conversation_memory": self._conversation,
                "relationship_memory": self._relationship,
                "goal_manager": self._goals,
                "procedural_memory": self._procedural,
                "crm": self._crm,
                "endocrine": self._endocrine,
            },
        }
        if enrichment_parts:
            context["enrichment"] = "\n\n".join(enrichment_parts)

        raw_response: str
        agents_used: list[str]

        if truth_hint_response is not None:
            raw_response = truth_hint_response
            agents_used = ["truth_hints"]
        elif route_method in ("deterministic", "procedural"):
            raw_response, agents_used = await self._execute_routed(
                agent_names, resolved_input, context,
            )
        else:
            raw_response = await self._pantheon.process(resolved_input, context)
            agents_used = ["athena"]

        trace["route"] = route_method
        trace["agents"] = agents_used
        logger.info("EXECUTE | route=%s agents=%s", route_method, agents_used)

        # ── 6.5 CLARIFICATION CHECK ──────────────────────────────────
        _CLARIFY_PREFIX = "[CLARIFY]"
        if raw_response.startswith(_CLARIFY_PREFIX):
            clarification_q = raw_response[len(_CLARIFY_PREFIX):].strip()
            self._pending_clarifications[sender_id] = {
                "agent_name": agents_used[0] if agents_used else "athena",
                "original_query": resolved_input,
                "clarification_question": clarification_q,
            }
            logger.info("CLARIFY | stored pending for %s (sender=%s)", contact_email, sender_id)
            shaped = await self._voice.shape_response(clarification_q, channel)
            return shaped

        # ── 7. ASSESS ────────────────────────────────────────────────
        confidence_prefix = ""
        if self._metacognition is not None:
            try:
                retriever = self._pantheon._retriever
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
            except Exception:
                logger.exception("Metacognition assessment failed")

        # ── 8. REFLECT ───────────────────────────────────────────────
        reflection_text = ""
        if self._inner_voice is not None:
            try:
                reflection = await self._inner_voice.reflect(
                    context=f"User ({contact_email}) on {channel}: {raw_input}",
                    trigger=raw_response[:500],
                )
                if reflection.get("should_surface") and reflection.get("content"):
                    reflection_text = f"\n\n_{reflection['content']}_"
            except Exception:
                logger.exception("InnerVoice reflection failed")

        # ── 9. SHAPE ─────────────────────────────────────────────────
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
            except Exception:
                logger.exception("Endocrine modifiers failed")

        shaped = await self._voice.shape_response(
            full_response,
            channel,
            recipient=recipient,
            behavioral_modifiers=modifiers,
        )

        logger.info("SHAPE | channel=%s len=%d", channel, len(shaped))

        # ── 10. LEARN ────────────────────────────────────────────────
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
        return shaped

    # ── Execution helpers ─────────────────────────────────────────────────

    async def _execute_routed(
        self,
        agent_names: list[str],
        query: str,
        context: dict[str, Any],
    ) -> tuple[str, list[str]]:
        """Execute one or more agents by name, returning (response, names_used)."""
        used: list[str] = []
        responses: dict[str, str] = {}

        for name in agent_names:
            agent = self._pantheon.get_agent(name)
            if agent is None:
                logger.warning("Agent '%s' not found — skipping", name)
                continue
            try:
                resp = await agent.handle(query, context)
                responses[name] = resp
                used.append(name)
            except Exception:
                logger.exception("Agent '%s' failed during execution", name)
                responses[name] = f"(Agent '{name}' encountered an error)"
                used.append(name)

        if not responses:
            return await self._pantheon.process(query, context), ["athena"]

        if len(responses) == 1:
            return next(iter(responses.values())), used

        athena = self._pantheon.get_agent("athena")
        if athena is not None:
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
        except Exception:
            logger.exception("ConversationMemory recording failed")

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
            except Exception:
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
            except Exception:
                logger.exception("MusculoskeletalSystem recording failed")

        # Goal slot extraction
        if active_goal is not None and self._goals is not None:
            try:
                extracted = await self._goals.extract_slots(active_goal, raw_input)
                if extracted:
                    await self._goals.update_goal(active_goal.id, extracted)
            except Exception:
                logger.exception("GoalManager slot update failed")

        # Goal detection for new goals
        if active_goal is None and self._goals is not None:
            try:
                await self._goals.detect_goal(
                    resolved_input,
                    {"contact_id": contact_email, "channel": channel},
                )
            except Exception:
                logger.exception("GoalManager detection failed")

        # Procedural learning
        if self._procedural is not None and route_method in ("deterministic", "llm"):
            try:
                await self._procedural.learn_procedure(
                    resolved_input, agents_used,
                )
            except Exception:
                logger.exception("ProceduralMemory learning failed")

        # Trigger Sophia for background reflection (fire-and-forget)
        sophia = self._pantheon.get_agent("sophia")
        if sophia is not None:
            try:
                await sophia.handle(
                    f"Reflect on this interaction: {raw_input[:300]}",
                    {"response": raw_response[:300], "route": route_method},
                )
            except Exception:
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
        except Exception:
            logger.warning("RealTimeObserver not available", exc_info=True)

        # Endocrine feedback
        if self._endocrine is not None:
            try:
                self._endocrine.boost("growth_signal", 0.02)
                if route_method == "deterministic":
                    self._endocrine.boost("confidence", 0.01)
            except Exception:
                logger.warning("Endocrine update failed", exc_info=True)

        if self._unified_ctx is not None:
            try:
                self._unified_ctx.record_turn(
                    contact_email, channel, raw_input, raw_response,
                )
            except Exception:
                logger.exception("UnifiedContextManager recording failed")

        logger.info("LEARN | recorded for %s", contact_email)
