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


class DisambiguationPayload(BaseModel):
    """Callback payload for disambiguation selection."""

    task_id: str
    option_index: int

    def encode(self) -> str:
        return f"disambig:{self.task_id}:{self.option_index}"

    @classmethod
    def decode(cls, data: str) -> "DisambiguationPayload":
        parts = data.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid disambiguation callback data: {data!r}")
        _, task_id, idx = parts
        return cls(task_id=task_id, option_index=int(idx))


class DraftActionPayload(BaseModel):
    """Callback payload for draft message actions (use, shorter, formal)."""

    action: str  # "draft_use", "draft_shorter", "draft_formal"
    task_id: str

    def encode(self) -> str:
        return f"{self.action}:{self.task_id}"

    @classmethod
    def decode(cls, data: str) -> "DraftActionPayload":
        parts = data.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid draft callback data: {data!r}")
        action, task_id = parts
        return cls(action=action, task_id=task_id)


class QueueActionPayload(BaseModel):
    """Callback payload for queue actions (start, batch, ambiguous, pause)."""

    action: str  # "queue:start", "queue:batch:5", "queue:ambiguous", "queue:pause"

    def encode(self) -> str:
        return self.action

    @classmethod
    def decode(cls, data: str) -> "QueueActionPayload":
        if not data.startswith("queue:"):
            raise ValueError(f"Invalid queue callback data: {data!r}")
        return cls(action=data)

    @property
    def sub_action(self) -> str:
        """Return the action part after 'queue:' (e.g., 'start', 'batch:5', 'pause')."""
        return self.action[len("queue:") :]

    @property
    def batch_size(self) -> int | None:
        """Extract batch size if this is a batch action, else None."""
        sub = self.sub_action
        if sub.startswith("batch:"):
            try:
                return int(sub.split(":", 1)[1])
            except (ValueError, IndexError):
                return None
        return None


class SettingPayload(BaseModel):
    """Callback payload for settings toggles."""

    key: str  # setting key, e.g., "auto_next", "batch_size"

    def encode(self) -> str:
        return f"setting:{self.key}"

    @classmethod
    def decode(cls, data: str) -> "SettingPayload":
        parts = data.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid setting callback data: {data!r}")
        _, key = parts
        return cls(key=key)
