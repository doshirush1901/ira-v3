"""Pydantic models for structured LLM outputs.

Every JSON schema that was previously parsed via ``json.loads()`` from raw
LLM text is defined here as a Pydantic model.  These models are used with
``LLMClient.generate_structured()`` for type-safe, validated responses.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── ReAct loop ────────────────────────────────────────────────────────────


class ToolCall(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ReActDecision(BaseModel):
    thought: str = ""
    tool_to_use: ToolCall | None = None
    final_answer: str | None = None


# ── Feedback ──────────────────────────────────────────────────────────────


class FeedbackClassification(BaseModel):
    polarity: str = "neutral"
    confidence: float = 0.5
    extracted_correction: str | None = None


# ── Retriever ─────────────────────────────────────────────────────────────


class EntityNames(BaseModel):
    entities: list[str] = Field(default_factory=list)


class SubQueries(BaseModel):
    queries: list[str] = Field(default_factory=list)


# ── Imports metadata ──────────────────────────────────────────────────────


class DocumentMetadata(BaseModel):
    summary: str = ""
    doc_type: str = ""
    machines: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


# ── Knowledge graph ───────────────────────────────────────────────────────


class CompanyEntity(BaseModel):
    name: str = ""
    region: str = ""
    industry: str = ""
    website: str = ""


class PersonEntity(BaseModel):
    name: str = ""
    email: str = ""
    company: str = ""
    role: str = ""


class MachineEntity(BaseModel):
    model: str = ""
    category: str = ""
    description: str = ""


class GraphRelationship(BaseModel):
    from_type: str = ""
    from_key: str = ""
    rel: str = ""
    to_type: str = ""
    to_key: str = ""


class GraphEntities(BaseModel):
    companies: list[CompanyEntity] = Field(default_factory=list)
    people: list[PersonEntity] = Field(default_factory=list)
    machines: list[MachineEntity] = Field(default_factory=list)
    relationships: list[GraphRelationship] = Field(default_factory=list)


# ── Digestive system ─────────────────────────────────────────────────────


class NutrientClassification(BaseModel):
    protein: list[str] = Field(default_factory=list)
    carbs: list[str] = Field(default_factory=list)
    waste: list[str] = Field(default_factory=list)


class DigestiveSummary(BaseModel):
    statements: list[str] = Field(default_factory=list)


class EmailSenderInfo(BaseModel):
    name: str = ""
    email: str = ""
    company: str = ""
    role: str = ""


class EmailMetadata(BaseModel):
    sender_info: EmailSenderInfo = Field(default_factory=EmailSenderInfo)
    company_mentions: list[str] = Field(default_factory=list)
    machine_mentions: list[str] = Field(default_factory=list)
    pricing_mentions: list[str] = Field(default_factory=list)
    dates_deadlines: list[str] = Field(default_factory=list)


# ── Emotional intelligence ───────────────────────────────────────────────


class EmotionDetection(BaseModel):
    state: str = "NEUTRAL"
    intensity: str = "MILD"
    indicators: list[str] = Field(default_factory=list)


# ── Goal manager ─────────────────────────────────────────────────────────


class GoalDetection(BaseModel):
    should_initiate: bool = False
    goal_type: str = ""
    reason: str = ""


class GoalSlots(BaseModel):
    slots: dict[str, str | None] = Field(default_factory=dict)


# ── Inner voice ──────────────────────────────────────────────────────────


class InnerReflection(BaseModel):
    reflection_type: str = "OBSERVATION"
    content: str = ""
    should_surface: bool = False


# ── Metacognition ────────────────────────────────────────────────────────


class KnowledgeAssessment(BaseModel):
    state: str = "PARTIAL"
    confidence: float = 0.5
    conflicts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


# ── Conversation memory ──────────────────────────────────────────────────


class ConversationEntities(BaseModel):
    companies: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    machines: list[str] = Field(default_factory=list)
    quote_ids: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    amounts: list[str] = Field(default_factory=list)


# ── Episodic memory ──────────────────────────────────────────────────────


class EpisodeConsolidation(BaseModel):
    narrative: str = ""
    key_topics: list[str] = Field(default_factory=list)
    decisions_made: list[str] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)
    memorable_moments: list[str] = Field(default_factory=list)
    emotional_tone: str = ""
    relationship_impact: str = "maintained"


# ── Relationship memory ──────────────────────────────────────────────────


class MemorableMoment(BaseModel):
    type: str = ""
    content: str = ""
    importance: str = "medium"


class MemorableMoments(BaseModel):
    moments: list[MemorableMoment | str] = Field(default_factory=list)


# ── Procedural memory ────────────────────────────────────────────────────


class PatternExtraction(BaseModel):
    trigger: str = ""
    steps: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    category: str = ""


# ── Dream mode ────────────────────────────────────────────────────────────


class DreamInsight(BaseModel):
    patterns: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class DreamGap(BaseModel):
    topic: str = ""
    description: str = ""
    priority: str = ""
    related_queries: list[str] = Field(default_factory=list)


class DreamGaps(BaseModel):
    gaps: list[DreamGap] = Field(default_factory=list)


class DreamConnection(BaseModel):
    insight: str = ""
    supporting_evidence: list[str] = Field(default_factory=list)
    confidence: str = ""


class DreamCreative(BaseModel):
    connections: list[DreamConnection] = Field(default_factory=list)


class DreamCampaignInsights(BaseModel):
    insights: list[str] = Field(default_factory=list)


class DreamProcedure(BaseModel):
    trigger: str = ""
    steps: list[str] = Field(default_factory=list)
    expected_outcome: str = ""
    confidence: str = ""


class DreamProcedures(BaseModel):
    procedures: list[DreamProcedure] = Field(default_factory=list)


class DreamPruneSummary(BaseModel):
    ids: list[str] = Field(default_factory=list)
    summary: str = ""


class DreamPrune(BaseModel):
    keep: list[str] = Field(default_factory=list)
    summarise: list[DreamPruneSummary] = Field(default_factory=list)
    archive: list[str] = Field(default_factory=list)


# ── Sleep trainer ─────────────────────────────────────────────────────────


class TruthHint(BaseModel):
    pattern: str = ""
    answer: str = ""
    entity: str = ""
    category: str = ""


class TruthHints(BaseModel):
    hints: list[TruthHint] = Field(default_factory=list)


# ── Realtime observer ────────────────────────────────────────────────────


class ObservedTurn(BaseModel):
    facts: list[str] = Field(default_factory=list)
    corrections: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


# ── Knowledge discovery ──────────────────────────────────────────────────


class KnowledgeGap(BaseModel):
    gap_type: str = ""
    description: str = ""
    suggested_search: str = ""


class DeepFact(BaseModel):
    content: str = ""
    entity: str = ""
    category: str = ""


class DeepFacts(BaseModel):
    facts: list[DeepFact] = Field(default_factory=list)


# ── Learning hub ─────────────────────────────────────────────────────────


class CorrectionAnalysis(BaseModel):
    error_category: str = ""
    what_was_wrong: str = ""
    correct_behaviour: str = ""


class GapAnalysis(BaseModel):
    gap_type: str = ""
    description: str = ""
    suggested_skill_name: str = ""
    suggested_skill_description: str = ""
    suggested_knowledge_source: str = ""


class ProcedureSteps(BaseModel):
    steps: list[str] = Field(default_factory=list)


# ── Quotes ────────────────────────────────────────────────────────────────


class MachineInfo(BaseModel):
    machine_model: str = ""
    configuration: dict[str, Any] = Field(default_factory=dict)
