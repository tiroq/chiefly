from pydantic import BaseModel, Field, field_validator

from core.domain.enums import ConfidenceBand, TaskKind


class TaskClassificationResult(BaseModel):
    """Legacy single-call classification result. Kept for backward compatibility."""

    kind: TaskKind
    normalized_title: str = Field(min_length=1, max_length=500)
    project_guess: str | None = None
    project_confidence: ConfidenceBand = ConfidenceBand.LOW
    next_action: str | None = None
    due_hint: str | None = None
    substeps: list[str] = Field(default_factory=list)
    confidence: ConfidenceBand = ConfidenceBand.MEDIUM
    ambiguities: list[str] = Field(default_factory=list)
    notes_for_user: str | None = None
    internal_rationale: str | None = None

    @field_validator("normalized_title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        return v.strip()

    @field_validator("substeps", mode="before")
    @classmethod
    def ensure_substeps_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []

    @field_validator("ambiguities", mode="before")
    @classmethod
    def ensure_ambiguities_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []


class NormalizationResult(BaseModel):
    """Step 1: Raw text → normalized intent + rewritten English title."""

    intent_summary: str = Field(min_length=1, max_length=500)
    rewritten_title: str = Field(default="", max_length=200)
    is_multi_item: bool = False
    entities: list[str] = Field(default_factory=list)
    language: str = Field(default="en", pattern=r"^(ru|en|mixed)$")

    @field_validator("intent_summary")
    @classmethod
    def strip_intent(cls, v: str) -> str:
        return v.strip()

    @field_validator("rewritten_title")
    @classmethod
    def strip_rewritten_title(cls, v: str) -> str:
        return v.strip()

    @field_validator("entities", mode="before")
    @classmethod
    def ensure_entities_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []


class ClassifyRouteResult(BaseModel):
    """Step 2: Classification + routing + title + next action (combined for MVP)."""

    type: TaskKind
    project: str = Field(min_length=1, max_length=255)
    confidence: ConfidenceBand = ConfidenceBand.MEDIUM
    reasoning: str = Field(default="", max_length=500)
    title: str = Field(min_length=1)
    next_action: str = Field(default="")
    due_hint: str | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        return v.strip()[:200]

    @field_validator("next_action")
    @classmethod
    def strip_next_action(cls, v: str) -> str:
        return v.strip()[:200]

    @field_validator("project")
    @classmethod
    def strip_project(cls, v: str) -> str:
        return v.strip()

    @field_validator("reasoning")
    @classmethod
    def strip_reasoning(cls, v: str) -> str:
        return v.strip()[:500]


class DescriptionResult(BaseModel):
    """Step 3 (optional): Task description."""

    description: str = Field(min_length=1)

    @field_validator("description")
    @classmethod
    def strip_description(cls, v: str) -> str:
        return v.strip()[:1000]


class StepsResult(BaseModel):
    """Step 4 (optional): Task breakdown."""

    steps: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("steps", mode="before")
    @classmethod
    def ensure_steps_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(s).strip() for s in v if s][:10]
        return []


class AmbiguityOption(BaseModel):
    """Single disambiguation option for low-confidence items."""

    type: TaskKind
    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=300)


class DisambiguationResult(BaseModel):
    """Step for low-confidence items: 2-3 possible interpretations."""

    options: list[AmbiguityOption] = Field(min_length=1, max_length=3)


class PipelineResult(BaseModel):
    """Final combined output of the multi-step LLM pipeline.

    Designed to be backward-compatible: can produce a TaskClassificationResult
    via to_legacy() for existing consumers (RevisionService, etc.).
    """

    type: TaskKind
    project: str
    title: str = Field(min_length=1, max_length=200)
    next_action: str = Field(default="")
    confidence: ConfidenceBand = ConfidenceBand.MEDIUM

    intent_summary: str = ""
    language: str = "en"
    is_multi_item: bool = False
    entities: list[str] = Field(default_factory=list)

    description: str | None = None
    steps: list[str] = Field(default_factory=list)
    due_hint: str | None = None
    reasoning: str = ""

    disambiguation_options: list[AmbiguityOption] = Field(default_factory=list)

    def to_legacy(self) -> TaskClassificationResult:
        """Convert to TaskClassificationResult for backward compatibility."""
        return TaskClassificationResult(
            kind=self.type,
            normalized_title=self.title,
            project_guess=self.project,
            project_confidence=self.confidence,
            next_action=self.next_action or None,
            due_hint=self.due_hint,
            substeps=self.steps,
            confidence=self.confidence,
            ambiguities=[],
            notes_for_user=self.description,
            internal_rationale=self.reasoning,
        )
