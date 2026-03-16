"""Load and expose the recruitment scoring system (dimensions + weights).

Default system lives in data/knowledge/recruitment_scoring_system.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ira.schemas.anu_outputs import ScoringDimension

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _REPO_ROOT / "data" / "knowledge" / "recruitment_scoring_system.json"


def load_scoring_system(path: Path | None = None) -> dict[str, Any]:
    """Load the scoring system JSON (name, role_default, dimensions). Returns dict; dimensions are raw dicts."""
    p = path or _DEFAULT_PATH
    if not p.exists():
        logger.warning("Recruitment scoring system file not found: %s", p)
        return _default_system_fallback()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        dims = data.get("dimensions") or []
        if not dims:
            return _default_system_fallback()
        return data
    except Exception as e:
        logger.warning("Failed to load recruitment scoring system from %s: %s", p, e)
        return _default_system_fallback()


def get_dimensions(path: Path | None = None) -> list[ScoringDimension]:
    """Return scoring dimensions as Pydantic models (for Anu and API)."""
    data = load_scoring_system(path)
    dims = data.get("dimensions") or []
    out = []
    for d in dims:
        try:
            out.append(ScoringDimension(**d))
        except Exception as e:
            logger.debug("Skip invalid dimension %s: %s", d, e)
    return out


def _default_system_fallback() -> dict[str, Any]:
    """In-memory default if file is missing."""
    return {
        "name": "Default Machinecraft Recruitment",
        "role_default": "Procurement",
        "dimensions": [
            {"id": "experience", "name": "Relevant experience", "description": "Experience in procurement/supply chain.", "weight": 0.25},
            {"id": "skills_fit", "name": "Skills fit", "description": "Match to role (Tally, PO, vendor coordination).", "weight": 0.25},
            {"id": "communication", "name": "Communication", "description": "Clarity and professionalism.", "weight": 0.2},
            {"id": "relocation_commitment", "name": "Relocation / commitment", "description": "Willingness to relocate to Umargam.", "weight": 0.1},
            {"id": "case_study", "name": "Case study", "description": "Problem-solving and prioritisation.", "weight": 0.2},
        ],
    }
