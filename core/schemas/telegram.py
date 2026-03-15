from pydantic import BaseModel

from core.domain.enums import ReviewAction


class CallbackPayload(BaseModel):
    """Compact callback data schema for Telegram inline keyboards."""

    action: ReviewAction
    task_id: str  # short UUID hex

    def encode(self) -> str:
        return f"{self.action}:{self.task_id}"

    @classmethod
    def decode(cls, data: str) -> "CallbackPayload":
        parts = data.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid callback data: {data!r}")
        action, task_id = parts
        return cls(action=ReviewAction(action), task_id=task_id)


class ProjectSelectPayload(BaseModel):
    """Callback payload for project selection."""

    task_id: str
    project_slug: str

    def encode(self) -> str:
        return f"proj:{self.task_id}:{self.project_slug}"

    @classmethod
    def decode(cls, data: str) -> "ProjectSelectPayload":
        parts = data.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid project callback data: {data!r}")
        _, task_id, project_slug = parts
        return cls(task_id=task_id, project_slug=project_slug)


class KindSelectPayload(BaseModel):
    """Callback payload for kind selection."""

    task_id: str
    kind: str

    def encode(self) -> str:
        return f"kind:{self.task_id}:{self.kind}"

    @classmethod
    def decode(cls, data: str) -> "KindSelectPayload":
        parts = data.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid kind callback data: {data!r}")
        _, task_id, kind = parts
        return cls(task_id=task_id, kind=kind)
