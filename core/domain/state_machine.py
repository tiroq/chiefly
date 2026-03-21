from core.domain.enums import TaskStatus
from core.domain.exceptions import InvalidStateTransitionError

# Allowed transitions: {from_status: set_of_valid_to_statuses}
# ANY -> ERROR is allowed for all states where an operational error can occur.
# COMPLETED and DISCARDED are terminal for normal flow, but can still transition
# to ERROR to record unexpected post-completion failures (e.g. Google Tasks sync).
ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.NEW: {TaskStatus.PROPOSED, TaskStatus.ERROR},
    TaskStatus.PROPOSED: {TaskStatus.CONFIRMED, TaskStatus.DISCARDED, TaskStatus.ERROR},
    TaskStatus.CONFIRMED: {TaskStatus.ROUTED, TaskStatus.ERROR},
    TaskStatus.ROUTED: {TaskStatus.COMPLETED, TaskStatus.ERROR},
    TaskStatus.COMPLETED: {TaskStatus.ERROR},
    TaskStatus.DISCARDED: {TaskStatus.ERROR},
    TaskStatus.ERROR: {TaskStatus.NEW},
}


def transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    """
    Validate and apply a status transition.

    Raises InvalidStateTransitionError if the transition is not allowed.
    Returns the target status if the transition is valid.
    """
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"Transition from {current!r} to {target!r} is not allowed. "
            f"Allowed targets: {sorted(s.value for s in allowed)}"
        )
    return target


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Return True if the transition is allowed without raising."""
    return target in ALLOWED_TRANSITIONS.get(current, set())
