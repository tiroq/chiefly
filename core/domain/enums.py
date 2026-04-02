from enum import StrEnum


class TaskKind(StrEnum):
    TASK = "task"
    WAITING = "waiting"
    COMMITMENT = "commitment"
    IDEA = "idea"
    REFERENCE = "reference"


class LegacyTaskStatus(StrEnum):
    NEW = "new"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    ROUTED = "routed"
    COMPLETED = "completed"
    DISCARDED = "discarded"
    ERROR = "error"


class ReviewAction(StrEnum):
    CONFIRM = "confirm"
    EDIT = "edit"
    CHANGE_PROJECT = "change_project"
    CHANGE_TYPE = "change_type"
    DISCARD = "discard"
    SHOW_STEPS = "show_steps"
    SKIP = "skip"
    CLARIFY = "clarify"
    DRAFT_MESSAGE = "draft_message"


class ProjectType(StrEnum):
    CLIENT = "client"
    PERSONAL = "personal"
    FAMILY = "family"
    OPS = "ops"
    WRITING = "writing"
    INTERNAL = "internal"


class ConfidenceBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    LOCKED = "locked"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ProcessingReason(StrEnum):
    NEW_TASK = "new_task_detected"
    SOURCE_CHANGED = "source_task_changed"
    TASK_MOVED = "task_moved_to_different_list"
    MANUAL_REPROCESS = "manual_reprocess_requested"
    PROMPT_VERSION_CHANGED = "prompt_version_changed"
    CLASSIFICATION_FAILED = "classification_failed"
    LOW_CONFIDENCE_REPROCESS = "low_confidence_reprocess"


class TaskRecordState(StrEnum):
    UNADOPTED = "unadopted"
    ACTIVE = "active"
    MISSING = "missing"
    DELETED = "deleted"
    ORPHANED = "orphaned"


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    APPLIED = "applied"
    FAILED = "failed"
    DISCARDED = "discarded"


class ReviewSessionStatus(StrEnum):
    QUEUED = "queued"           # processed, waiting in review queue (not yet shown)
    ACTIVE = "active"           # actively shown in Telegram / Mini App (was "pending")
    SEND_FAILED = "send_failed"  # failed to deliver to Telegram (retryable)
    SKIPPED = "skipped"         # user chose to skip
    RESOLVED = "resolved"       # user confirmed or discarded (terminal)
    DISCARDED = "discarded"
    FAILED = "failed"
