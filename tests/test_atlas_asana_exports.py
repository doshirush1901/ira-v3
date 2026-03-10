from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ira.agents.atlas import Atlas
from ira.message_bus import MessageBus


def _settings() -> MagicMock:
    settings = MagicMock()
    settings.app.react_max_iterations = 3
    settings.app.max_delegation_depth = 5
    settings.firecrawl.api_key.get_secret_value.return_value = ""
    settings.search.tavily_api_key.get_secret_value.return_value = ""
    settings.search.serper_api_key.get_secret_value.return_value = ""
    settings.search.searchapi_api_key.get_secret_value.return_value = ""
    return settings


@pytest.mark.asyncio
async def test_eto_daily_report_dedupes_copied_exports(tmp_path: Path):
    older = tmp_path / "sample.csv"
    newer = tmp_path / "sample (1).csv"
    older.write_text(
        "Task ID,Name,Section/Column,Projects,Created At,Completed At\n"
        "o1,O: Bearings,RFQs,Project Alpha,2022-10-08,\n",
        encoding="utf-8",
    )
    newer.write_text(
        "Task ID,Name,Section/Column,Projects,Created At,Completed At\n"
        "o2,O: Cylinders,RFQs,Project Alpha,2022-10-09,\n",
        encoding="utf-8",
    )
    # Ensure newer file sorts first by mtime.
    newer.touch()

    retriever = AsyncMock()
    retriever.search = AsyncMock(return_value=[])
    retriever.search_by_category = AsyncMock(return_value=[])

    mock_llm = MagicMock()
    mock_llm.generate_text_with_fallback = AsyncMock(return_value="ok")
    mock_llm.generate_text = AsyncMock(return_value="ok")

    with (
        patch("ira.agents.base_agent.get_llm_client", return_value=mock_llm),
        patch("ira.agents.base_agent.get_settings", return_value=_settings()),
        patch("ira.agents.atlas._ASANA_IMPORTS_DIR", tmp_path),
    ):
        atlas = Atlas(retriever=retriever, bus=MessageBus())
        raw = await atlas.eto_daily_report(max_files=8)
        report = json.loads(raw)

    assert report["status"] == "ok"
    assert report["source"]["csv_files_scanned"] == 1
    assert report["source"]["tasks_scanned"] == 1

