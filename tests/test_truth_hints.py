from __future__ import annotations

import json

import pytest

from ira.brain.truth_hints import TruthHintsEngine


@pytest.mark.asyncio
async def test_loads_list_format_hints(tmp_path):
    data_dir = tmp_path / "brain"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "truth_hints.json").write_text("[]", encoding="utf-8")
    (data_dir / "learned_truth_hints.json").write_text(json.dumps([
        {
            "patterns": [r"\bpf1\b"],
            "keywords": ["pf1"],
            "answer": "PF1 is available.",
        },
    ]), encoding="utf-8")

    engine = TruthHintsEngine(data_dir=data_dir)
    await engine._load()

    assert engine.get_stats()["learned"] == 1
    assert engine.match("Tell me about PF1") is not None


@pytest.mark.asyncio
async def test_loads_dict_with_hints_key(tmp_path):
    data_dir = tmp_path / "brain"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "truth_hints.json").write_text(json.dumps({
        "hints": [
            {
                "patterns": [r"\bpricing\b"],
                "keywords": ["price"],
                "answer": "Pricing depends on configuration.",
            },
        ],
    }), encoding="utf-8")
    (data_dir / "learned_truth_hints.json").write_text(json.dumps({"hints": []}), encoding="utf-8")

    engine = TruthHintsEngine(data_dir=data_dir)
    await engine._load()

    assert engine.get_stats()["manual"] == 1
    assert engine.match("What is the pricing?") is not None


@pytest.mark.asyncio
async def test_malformed_entries_are_filtered_not_dropped(tmp_path):
    data_dir = tmp_path / "brain"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "truth_hints.json").write_text(json.dumps([
        "not-a-dict",
        {"patterns": ["x"]},
        {"answer": "Valid answer", "patterns": [r"\bok\b"], "keywords": ["ok"]},
    ]), encoding="utf-8")
    (data_dir / "learned_truth_hints.json").write_text(json.dumps([]), encoding="utf-8")

    engine = TruthHintsEngine(data_dir=data_dir)
    await engine._load()

    stats = engine.get_stats()
    assert stats["manual"] == 1
    matched = engine.match("ok")
    assert matched is not None
    assert matched["answer"] == "Valid answer"
