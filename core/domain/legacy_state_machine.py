from core.domain.enums import LegacyTaskStatus
from core.domain.exceptions import InvalidStateTransitionError

# Allowed transitions: {from_status: set_of_valid_to_statuses}
# ANY -> ERROR is allowed for all states where an operational error can occur.
# COMPLETED and DISCARDED are terminal for normal flow, but can still transition
# to ERROR to record unexpected post-completion failures (e.g. Google Tasks sync).
ALLOWED_TRANSITIONS: dict[LegacyTaskStatus, set[LegacyTaskStatus]] = {
    LegacyTaskStatus.NEW: {LegacyTaskStatus.PROPOSED, LegacyTaskStatus.ERROR},
    LegacyTaskStatus.PROPOSED: {
        LegacyTaskStatus.CONFIRMED,
        LegacyTaskStatus.DISCARDED,
        LegacyTaskStatus.ERROR,
    },
    LegacyTaskStatus.CONFIRMED: {LegacyTaskStatus.ROUTED, LegacyTaskStatus.ERROR},
    LegacyTaskStatus.ROUTED: {LegacyTaskStatus.COMPLETED, LegacyTaskStatus.ERROR},
    LegacyTaskStatus.COMPLETED: {LegacyTaskStatus.ERROR},
    LegacyTaskStatus.DISCARDED: {LegacyTaskStatus.ERROR},
    LegacyTaskStatus.ERROR: {LegacyTaskStatus.NEW},
}


def transition(current: LegacyTaskStatus, target: LegacyTaskStatus) -> LegacyTaskStatus:
    """
    Validate and apply a status transition.

    Raises InvalidStateTransitionError if the transition is not allowed.
    Returns the target status if the transition is valid.
    """
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"Transition from {current!r} to {target!r} is not allowed. Allowed targets: {sorted(s.value for s in allowed)}"
        )
    return target


def can_transition(current: LegacyTaskStatus, target: LegacyTaskStatus) -> bool:
    """Return True if the transition is allowed without raising."""
    return target in ALLOWED_TRANSITIONS.get(current, set())
