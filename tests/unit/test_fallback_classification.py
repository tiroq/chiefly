"""
Unit tests for fallback classification heuristics in LLM service.
"""

import pytest

from apps.api.services.llm_service import _fallback_classification
from core.domain.enums import ConfidenceBand, TaskKind


class TestFallbackClassification:
    def test_waiting_russian_keyword(self):
        result = _fallback_classification("жду от alex сертификаты")
        assert result.kind == TaskKind.WAITING
        assert result.confidence == ConfidenceBand.LOW

    def test_waiting_english_keyword(self):
        result = _fallback_classification("waiting for Bob to respond")
        assert result.kind == TaskKind.WAITING

    def test_waiting_wait_for_keyword(self):
        result = _fallback_classification("wait for approval from legal")
        assert result.kind == TaskKind.WAITING

    def test_idea_prefix(self):
        result = _fallback_classification("idea: build a task dashboard")
        assert result.kind == TaskKind.IDEA
        assert result.normalized_title == "build a task dashboard"

    def test_idea_prefix_empty_after_strip(self):
        result = _fallback_classification("idea:")
        assert result.kind == TaskKind.IDEA
        # Falls back to full raw_text when stripped portion is empty
        assert result.normalized_title == "idea:"

    def test_commitment_russian_keyword(self):
        result = _fallback_classification("обещал отправить отчёт")
        assert result.kind == TaskKind.COMMITMENT

    def test_commitment_english_keyword(self):
        result = _fallback_classification("promised to deliver report by Friday")
        assert result.kind == TaskKind.COMMITMENT

    def test_default_is_task(self):
        result = _fallback_classification("buy groceries from the store")
        assert result.kind == TaskKind.TASK

    def test_confidence_always_low(self):
        for text in ["buy milk", "жду ответа", "idea: concept", "promised delivery"]:
            result = _fallback_classification(text)
            assert result.confidence == ConfidenceBand.LOW
            assert result.project_confidence == ConfidenceBand.LOW

    def test_title_truncation(self):
        long_text = "x" * 600
        result = _fallback_classification(long_text)
        assert len(result.normalized_title) <= 500

    def test_case_insensitive_matching(self):
        result = _fallback_classification("WAITING for delivery")
        assert result.kind == TaskKind.WAITING

    def test_mixed_case_idea(self):
        result = _fallback_classification("Idea: new feature concept")
        # Code lowercases input before checking prefix, so "Idea:" matches
        assert result.kind == TaskKind.IDEA
        assert result.normalized_title == "new feature concept"
