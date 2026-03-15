from pydantic import BaseModel, Field, field_validator

from core.domain.enums import ConfidenceBand, TaskKind


class TaskClassificationResult(BaseModel):
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
