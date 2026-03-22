class ChieflyError(Exception):
    """Base exception for all Chiefly errors."""


class InvalidStateTransitionError(ChieflyError):
    """Raised when an invalid task state transition is attempted."""


class TaskNotFoundError(ChieflyError):
    """Raised when a task item cannot be found."""


class ProjectNotFoundError(ChieflyError):
    """Raised when a project cannot be found."""


class LLMError(ChieflyError):
    """Raised when LLM classification fails."""


class GoogleTasksError(ChieflyError):
    """Raised when a Google Tasks API call fails."""


class TelegramError(ChieflyError):
    """Raised when a Telegram API call fails."""


class DuplicateTaskError(ChieflyError):
    """Raised when a duplicate task is detected."""


class LockAcquisitionError(ChieflyError):
    """Raised when a processing lock cannot be acquired."""


class SessionNotFoundError(ChieflyError):
    """Raised when a Telegram review session cannot be found."""


class RollbackError(ChieflyError):
    """Raised when a rollback operation fails."""


class RollbackDriftError(RollbackError):
    """Raised when the Google Task was modified externally since the last revision."""
