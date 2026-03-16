"""
Unit tests for the state machine.
"""

import pytest

from core.domain.enums import TaskStatus
from core.domain.exceptions import InvalidStateTransitionError
from core.domain.state_machine import can_transition, transition


class TestStateMachineTransition:
    def test_new_to_proposed(self):
        result = transition(TaskStatus.NEW, TaskStatus.PROPOSED)
        assert result == TaskStatus.PROPOSED

    def test_proposed_to_confirmed(self):
        result = transition(TaskStatus.PROPOSED, TaskStatus.CONFIRMED)
        assert result == TaskStatus.CONFIRMED

    def test_proposed_to_discarded(self):
        result = transition(TaskStatus.PROPOSED, TaskStatus.DISCARDED)
        assert result == TaskStatus.DISCARDED

    def test_confirmed_to_routed(self):
        result = transition(TaskStatus.CONFIRMED, TaskStatus.ROUTED)
        assert result == TaskStatus.ROUTED

    def test_routed_to_completed(self):
        result = transition(TaskStatus.ROUTED, TaskStatus.COMPLETED)
        assert result == TaskStatus.COMPLETED

    def test_any_to_error(self):
        for status in (TaskStatus.NEW, TaskStatus.PROPOSED, TaskStatus.CONFIRMED, TaskStatus.ROUTED):
            result = transition(status, TaskStatus.ERROR)
            assert result == TaskStatus.ERROR

    def test_invalid_new_to_confirmed(self):
        with pytest.raises(InvalidStateTransitionError):
            transition(TaskStatus.NEW, TaskStatus.CONFIRMED)

    def test_invalid_new_to_routed(self):
        with pytest.raises(InvalidStateTransitionError):
            transition(TaskStatus.NEW, TaskStatus.ROUTED)

    def test_invalid_confirmed_to_proposed(self):
        with pytest.raises(InvalidStateTransitionError):
            transition(TaskStatus.CONFIRMED, TaskStatus.PROPOSED)

    def test_completed_to_error_allowed(self):
        result = transition(TaskStatus.COMPLETED, TaskStatus.ERROR)
        assert result == TaskStatus.ERROR

    def test_discarded_to_error_allowed(self):
        result = transition(TaskStatus.DISCARDED, TaskStatus.ERROR)
        assert result == TaskStatus.ERROR

    def test_invalid_completed_to_non_error(self):
        invalid_targets = [s for s in TaskStatus if s not in (TaskStatus.COMPLETED, TaskStatus.ERROR)]
        for target in invalid_targets:
            with pytest.raises(InvalidStateTransitionError):
                transition(TaskStatus.COMPLETED, target)

    def test_invalid_discarded_to_non_error(self):
        invalid_targets = [s for s in TaskStatus if s not in (TaskStatus.DISCARDED, TaskStatus.ERROR)]
        for target in invalid_targets:
            with pytest.raises(InvalidStateTransitionError):
                transition(TaskStatus.DISCARDED, target)

    def test_error_message_is_informative(self):
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            transition(TaskStatus.NEW, TaskStatus.ROUTED)
        assert "NEW" in str(exc_info.value) or "new" in str(exc_info.value).lower()
        assert "ROUTED" in str(exc_info.value) or "routed" in str(exc_info.value).lower()


class TestCanTransition:
    def test_valid_returns_true(self):
        assert can_transition(TaskStatus.NEW, TaskStatus.PROPOSED) is True

    def test_invalid_returns_false(self):
        assert can_transition(TaskStatus.NEW, TaskStatus.ROUTED) is False

    def test_completed_to_error_is_true(self):
        assert can_transition(TaskStatus.COMPLETED, TaskStatus.ERROR) is True

    def test_completed_to_non_error_is_false(self):
        for target in TaskStatus:
            if target != TaskStatus.ERROR:
                assert can_transition(TaskStatus.COMPLETED, target) is False
