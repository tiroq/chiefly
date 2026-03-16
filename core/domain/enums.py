from enum import StrEnum


class TaskKind(StrEnum):
    TASK = "task"
    WAITING = "waiting"
    COMMITMENT = "commitment"
    IDEA = "idea"
    REFERENCE = "reference"


class TaskStatus(StrEnum):
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
