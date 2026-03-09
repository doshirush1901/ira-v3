"""
Meeting notes → action items. Extracts structured action items from meeting text.
"""
import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("ira.meeting_actions")

try:
    import openai
    _client = openai.AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    OPENAI_AVAILABLE = True
except Exception:
    _client = None
    OPENAI_AVAILABLE = False


async def meeting_notes_to_actions(meeting_notes: str, max_items: int = 15) -> str:
    """
    Parse meeting notes and return a list of action items (action, owner, due).
    Uses LLM when available; otherwise returns a placeholder message.
    """
    if not (meeting_notes or meeting_notes.strip()):
        return "No meeting notes provided."

    if not OPENAI_AVAILABLE or not _client:
        return "(OpenAI not available. Install openai and set OPENAI_API_KEY to extract action items.)"

    try:
        resp = await _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": (
                    "Extract action items from the meeting notes. "
                    "Return a JSON array of objects with keys: action (string), owner (string or empty), due (string or empty). "
                    "Be concise. Maximum 15 items. If no clear action items, return []."
                )},
                {"role": "user", "content": meeting_notes[:6000]},
            ],
            max_tokens=800,
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        items = json.loads(text)
        if not isinstance(items, list):
            return "Could not parse action items."
        lines = ["# Action items from meeting", ""]
        for i, row in enumerate(items[:max_items], 1):
            action = row.get("action", str(row))
            owner = row.get("owner", "")
            due = row.get("due", "")
            line = f"{i}. **{action}**"
            if owner:
                line += f" — {owner}"
            if due:
                line += f" (due: {due})"
            lines.append(line)
        return "\n".join(lines) if len(lines) > 2 else "No action items identified."
    except json.JSONDecodeError as e:
        logger.warning("Meeting actions JSON parse failed: %s", e)
        return "Could not parse action items from response."
    except Exception as e:
        logger.warning("Meeting notes to actions failed: %s", e)
        return f"(Error extracting action items: {e})"
