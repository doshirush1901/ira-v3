from __future__ import annotations

import pytest

from ira.pipeline_loop import AgentLoop


class _MockAthena:
    def __init__(self, response: str) -> None:
        self._response = response

    async def call_llm(self, *_args, **_kwargs) -> str:
        return self._response


class _MockPantheon:
    def __init__(self, athena: _MockAthena) -> None:
        self._athena = athena
        self.agents = {"athena": athena, "clio": object(), "calliope": object()}

    def get_agent(self, name: str):
        if name == "athena":
            return self._athena
        return None


@pytest.mark.asyncio
async def test_plan_parses_valid_json_payload() -> None:
    raw = """
{
  "goal": "Analyze PF1 pipeline",
  "complexity": "moderate",
  "phases": [
    {
      "id": 1,
      "title": "Collect CRM data",
      "description": "Gather PF1 deal data",
      "agents": ["prometheus"],
      "delegation_type": "revenue",
      "expected_output": "Deal table",
      "depends_on": []
    }
  ]
}
"""
    loop = AgentLoop(_MockPantheon(_MockAthena(raw)))
    plan = await loop.plan("Analyze PF1 pipeline")
    assert plan.goal == "Analyze PF1 pipeline"
    assert len(plan.phases) == 1
    assert plan.phases[0].agents == ["prometheus"]


@pytest.mark.asyncio
async def test_plan_parses_fenced_json_payload() -> None:
    raw = """```json
{
  "goal": "Build proposal",
  "phases": [
    {"id": 1, "title": "Research", "description": "Collect facts", "agents": ["clio"]}
  ]
}
```"""
    loop = AgentLoop(_MockPantheon(_MockAthena(raw)))
    plan = await loop.plan("Build proposal")
    assert plan.goal == "Build proposal"
    assert plan.phases[0].title == "Research"


@pytest.mark.asyncio
async def test_plan_fallback_when_json_is_invalid() -> None:
    loop = AgentLoop(_MockPantheon(_MockAthena("not-json")))
    plan = await loop.plan("What should we do next?")
    assert len(plan.phases) == 2
    assert plan.phases[0].agents == ["clio"]
    assert plan.phases[1].agents == ["calliope"]
