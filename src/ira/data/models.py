"""Core data-transfer objects used across the Ira application.

These are Pydantic models for validation and serialization — not ORM/database
models.  Every agent, system, and interface speaks this shared vocabulary.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class DealStage(str, Enum):
    """Lifecycle stage of a sales deal."""

    NEW = "NEW"
    CONTACTED = "CONTACTED"
    ENGAGED = "ENGAGED"
    QUALIFIED = "QUALIFIED"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class Channel(str, Enum):
    """Communication channel for an interaction."""

    EMAIL = "EMAIL"
    TELEGRAM = "TELEGRAM"
    PHONE = "PHONE"
    MEETING = "MEETING"
    WEB = "WEB"


class Direction(str, Enum):
    """Whether a message was inbound (received) or outbound (sent)."""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class KnowledgeState(str, Enum):
    """How confident Ira is about a piece of knowledge."""

    KNOW_VERIFIED = "KNOW_VERIFIED"
    KNOW_UNVERIFIED = "KNOW_UNVERIFIED"
    PARTIAL = "PARTIAL"
    UNCERTAIN = "UNCERTAIN"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


class EmotionalState(str, Enum):
    """Ira's inferred emotional context for a conversation."""

    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"
    STRESSED = "STRESSED"
    FRUSTRATED = "FRUSTRATED"
    CURIOUS = "CURIOUS"
    URGENT = "URGENT"
    GRATEFUL = "GRATEFUL"
    UNCERTAIN = "UNCERTAIN"


class WarmthLevel(str, Enum):
    """Relationship warmth between Ira and a contact."""

    STRANGER = "STRANGER"
    ACQUAINTANCE = "ACQUAINTANCE"
    FAMILIAR = "FAMILIAR"
    WARM = "WARM"
    TRUSTED = "TRUSTED"


# ── Transfer Models ──────────────────────────────────────────────────────────


class KnowledgeItem(BaseModel):
    """A single chunk of ingested knowledge stored in the vector database."""

    id: UUID = Field(default_factory=uuid4, description="Unique identifier")
    source: str = Field(..., description="Origin file path or URL")
    source_category: str = Field(
        ...,
        description="One of the 22 import categories (e.g. 'machine_specs', 'pricing')",
    )
    content: str = Field(..., description="The text content of this knowledge chunk")
    metadata: dict = Field(default_factory=dict, description="Arbitrary key-value metadata")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Ingestion timestamp")


class Email(BaseModel):
    """An email message received or sent by Ira."""

    id: str = Field(..., description="Provider-assigned message ID")
    from_address: str = Field(..., description="Sender email address")
    to_address: str = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject line")
    body: str = Field(..., description="Plain-text email body")
    received_at: datetime = Field(..., description="When the email was received")
    thread_id: Optional[str] = Field(None, description="Conversation thread ID if available")
    labels: list[str] = Field(default_factory=list, description="Gmail/provider labels")


class Contact(BaseModel):
    """A person or company Ira tracks in the CRM."""

    id: UUID = Field(default_factory=uuid4, description="Unique identifier")
    name: str = Field(..., description="Full name of the contact")
    email: str = Field(..., description="Primary email address")
    company: Optional[str] = Field(None, description="Company or organization name")
    region: Optional[str] = Field(None, description="Geographic region (e.g. 'MENA', 'EU')")
    industry: Optional[str] = Field(None, description="Industry vertical")
    source: str = Field(..., description="How this contact was acquired (e.g. 'web_form', 'referral')")
    score: float = Field(0.0, description="Lead score from 0 to 100")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="When the contact was created")


class Deal(BaseModel):
    """A sales opportunity tied to a contact."""

    id: UUID = Field(default_factory=uuid4, description="Unique identifier")
    contact_id: UUID = Field(..., description="FK to the associated Contact")
    title: str = Field(..., description="Short description of the deal")
    value: float = Field(..., description="Monetary value of the deal")
    currency: str = Field("USD", description="ISO 4217 currency code")
    stage: DealStage = Field(DealStage.NEW, description="Current pipeline stage")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Deal creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")


class Interaction(BaseModel):
    """A logged touchpoint between Ira (or a human) and a contact."""

    id: UUID = Field(default_factory=uuid4, description="Unique identifier")
    contact_id: UUID = Field(..., description="FK to the associated Contact")
    channel: Channel = Field(..., description="Communication channel used")
    direction: Direction = Field(..., description="Inbound or outbound")
    summary: str = Field(..., description="One-line summary of the interaction")
    content: Optional[str] = Field(None, description="Full content or transcript if available")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="When the interaction occurred")


class AgentMessage(BaseModel):
    """An internal message passed between Pantheon agents via the message bus."""

    from_agent: str = Field(..., description="Name of the sending agent")
    to_agent: str = Field(..., description="Name of the receiving agent")
    query: str = Field(..., description="The request or instruction")
    context: dict = Field(default_factory=dict, description="Supplementary context for the request")
    response: Optional[str] = Field(None, description="The agent's response (filled after processing)")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Message timestamp")


class BoardMeetingMinutes(BaseModel):
    """Record of a Pantheon board meeting where agents collaborate on a topic."""

    topic: str = Field(..., description="The agenda item or question discussed")
    participants: list[str] = Field(..., description="Agent names that participated")
    contributions: dict[str, str] = Field(
        ...,
        description="Mapping of agent name to their contribution summary",
    )
    synthesis: str = Field(..., description="Final synthesized answer or decision")
    action_items: list[str] = Field(default_factory=list, description="Follow-up tasks")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Meeting timestamp")


class DripCampaignStep(BaseModel):
    """A single step in an automated drip email campaign for a lead."""

    lead_id: UUID = Field(..., description="FK to the Contact being nurtured")
    step_number: int = Field(..., description="Sequence position in the campaign (1-based)")
    email_subject: str = Field(..., description="Subject line for this step's email")
    email_body: str = Field(..., description="Body content for this step's email")
    sent_at: Optional[datetime] = Field(None, description="When the email was actually sent")
    reply_received: bool = Field(False, description="Whether the lead replied to this step")


class DreamReport(BaseModel):
    """Output of Ira's nightly dream-mode consolidation cycle."""

    cycle_date: date = Field(..., description="The date this dream cycle ran")
    memories_consolidated: int = Field(..., description="Number of memories processed")
    gaps_identified: list[str] = Field(
        default_factory=list,
        description="Knowledge gaps discovered during consolidation",
    )
    creative_connections: list[str] = Field(
        default_factory=list,
        description="Novel cross-domain connections surfaced",
    )
    campaign_insights: list[str] = Field(
        default_factory=list,
        description="Sales/marketing insights generated from pattern analysis",
    )
