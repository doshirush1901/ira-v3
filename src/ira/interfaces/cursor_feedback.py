"""Cursor-specific feedback loop for teaching Ira from corrections.

Thin wrapper around :class:`~ira.brain.feedback_handler.FeedbackHandler`
designed for use from the ``ira learn-from-cursor`` CLI command.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def process_cursor_feedback(
    query: str,
    response: str,
    correction: str,
    feedback: str = "",
) -> dict[str, Any]:
    """Process a correction submitted via the Cursor learning loop.

    Builds a minimal FeedbackHandler and routes the correction through
    the standard feedback pipeline (correction store, procedural memory,
    micro-learning cycle for high-severity corrections).
    """
    from ira.brain.correction_store import CorrectionStore
    from ira.brain.feedback_handler import FeedbackHandler
    from ira.memory.procedural import ProceduralMemory
    from ira.systems.learning_hub import LearningHub

    correction_store = CorrectionStore()
    await correction_store.initialize()

    procedural_memory = ProceduralMemory()
    await procedural_memory.initialize()

    learning_hub = LearningHub(procedural_memory=procedural_memory)

    handler = FeedbackHandler(
        learning_hub=learning_hub,
        correction_store=correction_store,
        procedural_memory=procedural_memory,
    )
    await handler.load_scores()

    message = correction or feedback or "This response was incorrect."

    result = await handler.process_feedback(
        message=message,
        previous_query=query,
        previous_response=response,
        agents_used=[],
        user_id="cursor-user",
    )

    await correction_store.close()
    await procedural_memory.close()

    logger.info("Cursor feedback processed: polarity=%s", result.get("polarity"))
    return result
