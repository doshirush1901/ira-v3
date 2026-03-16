"""Structured outputs for Anu — AI Recruiter Agent.

Resume parsing, candidate scoring, and profile export.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ParsedCandidate(BaseModel):
    """Structured candidate profile extracted from a resume/CV."""

    name: str = Field(description="Full name of the candidate")
    email: str = Field(default="", description="Email address")
    phone: str = Field(default="", description="Phone number")
    location: str = Field(default="", description="City, region or country")
    current_role: str = Field(default="", description="Current or most recent job title")
    current_company: str = Field(default="", description="Current or most recent employer")
    skills: list[str] = Field(default_factory=list, description="List of skills (technologies, tools, domains)")
    experience_years: float | None = Field(default=None, description="Years of relevant experience if stated")
    education: list[str] = Field(default_factory=list, description="Degrees, institutions, years")
    summary: str = Field(default="", description="Brief professional summary or objective")
    experience_highlights: list[str] = Field(
        default_factory=list,
        description="Key roles, achievements, or bullet points from experience",
    )


class CandidateScore(BaseModel):
    """Score and rationale for a candidate (vs role or general employability)."""

    score: float = Field(description="Numeric score 1-5 (1=low fit, 5=strong fit)")
    label: str = Field(description="Classification e.g. Strong Fit, Medium Fit, Low Fit")
    rationale: str = Field(description="Short justification for the score")
    strengths: list[str] = Field(default_factory=list, description="Key strengths")
    gaps: list[str] = Field(default_factory=list, description="Gaps or concerns if any")


# ── Applicant scoring system (dimension-based) ──────────────────────────────


class ScoringDimension(BaseModel):
    """One dimension of the recruitment scoring system (e.g. Experience, Skills fit)."""

    id: str = Field(description="Unique key e.g. experience, skills_fit")
    name: str = Field(description="Display name")
    description: str = Field(default="", description="What this dimension measures")
    weight: float = Field(ge=0.0, le=1.0, description="Weight for overall score (dimensions should sum to 1)")


class DimensionScoreResult(BaseModel):
    """Score and rationale for one dimension (1-5)."""

    dimension_id: str = Field(description="Matches ScoringDimension.id")
    score: float = Field(ge=1.0, le=5.0, description="1=low, 5=strong")
    rationale: str = Field(description="Short justification for this dimension")


class ApplicantScore(BaseModel):
    """Full applicant score: weighted overall plus per-dimension scores. Stored in recruitment_candidates.score_json."""

    overall_score: float = Field(ge=1.0, le=5.0, description="Weighted overall 1-5")
    label: str = Field(description="e.g. Strong Fit, Medium Fit, Low Fit")
    rationale: str = Field(description="Short overall justification")
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    dimension_scores: list[DimensionScoreResult] = Field(
        default_factory=list,
        description="Score and rationale per dimension",
    )
    scored_at: str | None = Field(default=None, description="ISO datetime when scored")
    role_applied: str | None = Field(default=None, description="Role this score is for")
