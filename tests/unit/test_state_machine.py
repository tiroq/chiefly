"""
Unit tests for the state machine.
"""

import pytest

from core.domain.enums import LegacyTaskStatus
from core.domain.exceptions import InvalidStateTransitionError
from core.domain.legacy_state_machine import can_transition, transition


class TestStateMachineTransition:
    def test_new_to_proposed(self):
        result = transition(LegacyTaskStatus.NEW, LegacyTaskStatus.PROPOSED)
        assert result == LegacyTaskStatus.PROPOSED

    def test_proposed_to_confirmed(self):
        result = transition(LegacyTaskStatus.PROPOSED, LegacyTaskStatus.CONFIRMED)
        assert result == LegacyTaskStatus.CONFIRMED

    def test_proposed_to_discarded(self):
        result = transition(LegacyTaskStatus.PROPOSED, LegacyTaskStatus.DISCARDED)
        assert result == LegacyTaskStatus.DISCARDED

    def test_confirmed_to_routed(self):
        result = transition(LegacyTaskStatus.CONFIRMED, LegacyTaskStatus.ROUTED)
        assert result == LegacyTaskStatus.ROUTED

    def test_routed_to_completed(self):
        result = transition(LegacyTaskStatus.ROUTED, LegacyTaskStatus.COMPLETED)
        assert result == LegacyTaskStatus.COMPLETED

    def test_any_to_error(self):
        for status in (
            LegacyTaskStatus.NEW,
            LegacyTaskStatus.PROPOSED,
            LegacyTaskStatus.CONFIRMED,
            LegacyTaskStatus.ROUTED,
        ):
            result = transition(status, LegacyTaskStatus.ERROR)
            assert result == LegacyTaskStatus.ERROR

    def test_invalid_new_to_confirmed(self):
        with pytest.raises(InvalidStateTransitionError):
            transition(LegacyTaskStatus.NEW, LegacyTaskStatus.CONFIRMED)

    def test_invalid_new_to_routed(self):
        with pytest.raises(InvalidStateTransitionError):
            transition(LegacyTaskStatus.NEW, LegacyTaskStatus.ROUTED)

    def test_invalid_confirmed_to_proposed(self):
        with pytest.raises(InvalidStateTransitionError):
            transition(LegacyTaskStatus.CONFIRMED, LegacyTaskStatus.PROPOSED)

    def test_completed_to_error_allowed(self):
        result = transition(LegacyTaskStatus.COMPLETED, LegacyTaskStatus.ERROR)
        assert result == LegacyTaskStatus.ERROR

    def test_discarded_to_error_allowed(self):
        result = transition(LegacyTaskStatus.DISCARDED, LegacyTaskStatus.ERROR)
        assert result == LegacyTaskStatus.ERROR

    def test_invalid_completed_to_non_error(self):
        invalid_targets = [
            s
            for s in LegacyTaskStatus
            if s not in (LegacyTaskStatus.COMPLETED, LegacyTaskStatus.ERROR)
        ]
        for target in invalid_targets:
            with pytest.raises(InvalidStateTransitionError):
                transition(LegacyTaskStatus.COMPLETED, target)

    def test_invalid_discarded_to_non_error(self):
        invalid_targets = [
            s
            for s in LegacyTaskStatus
            if s not in (LegacyTaskStatus.DISCARDED, LegacyTaskStatus.ERROR)
        ]
        for target in invalid_targets:
            with pytest.raises(InvalidStateTransitionError):
                transition(LegacyTaskStatus.DISCARDED, target)

    def test_error_message_is_informative(self):
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            transition(LegacyTaskStatus.NEW, LegacyTaskStatus.ROUTED)
        assert "NEW" in str(exc_info.value) or "new" in str(exc_info.value).lower()
        assert "ROUTED" in str(exc_info.value) or "routed" in str(exc_info.value).lower()


class TestCanTransition:
    def test_valid_returns_true(self):
        assert can_transition(LegacyTaskStatus.NEW, LegacyTaskStatus.PROPOSED) is True

    def test_invalid_returns_false(self):
        assert can_transition(LegacyTaskStatus.NEW, LegacyTaskStatus.ROUTED) is False

    def test_completed_to_error_is_true(self):
        assert can_transition(LegacyTaskStatus.COMPLETED, LegacyTaskStatus.ERROR) is True

    def test_completed_to_non_error_is_false(self):
        for target in LegacyTaskStatus:
            if target != LegacyTaskStatus.ERROR:
                assert can_transition(LegacyTaskStatus.COMPLETED, target) is False
