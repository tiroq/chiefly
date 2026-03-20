"""
Unit tests for Telegram proposal card rendering.
"""

import pytest

from apps.api.services.telegram_service import _build_proposal_text
from core.domain.enums import ConfidenceBand, TaskKind
from core.schemas.llm import TaskClassificationResult


class TestBuildProposalText:
    def _make_classification(self, **overrides) -> TaskClassificationResult:
        defaults = {
            "kind": TaskKind.TASK,
            "normalized_title": "Buy groceries",
            "confidence": ConfidenceBand.HIGH,
            "project_confidence": ConfidenceBand.HIGH,
        }
        defaults.update(overrides)
        return TaskClassificationResult(**defaults)

    def test_contains_raw_text(self):
        cls = self._make_classification()
        text = _build_proposal_text("raw input", cls, "Personal")
        assert "raw input" in text

    def test_contains_normalized_title(self):
        cls = self._make_classification(normalized_title="Formatted Title")
        text = _build_proposal_text("raw", cls, "Personal")
        assert "Formatted Title" in text

    def test_contains_project_name(self):
        cls = self._make_classification()
        text = _build_proposal_text("raw", cls, "NFT Gateway")
        assert "NFT Gateway" in text

    def test_no_project_shows_question_mark(self):
        cls = self._make_classification()
        text = _build_proposal_text("raw", cls, None)
        assert "?" in text

    def test_confidence_emoji_high(self):
        cls = self._make_classification(confidence=ConfidenceBand.HIGH)
        text = _build_proposal_text("raw", cls, "P")
        assert "🟢" in text

    def test_confidence_emoji_medium(self):
        cls = self._make_classification(confidence=ConfidenceBand.MEDIUM)
        text = _build_proposal_text("raw", cls, "P")
        assert "🟡" in text

    def test_confidence_emoji_low(self):
        cls = self._make_classification(confidence=ConfidenceBand.LOW)
        text = _build_proposal_text("raw", cls, "P")
        assert "🔴" in text

    def test_kind_labels_displayed(self):
        for kind, label_part in [
            (TaskKind.TASK, "Task"),
            (TaskKind.WAITING, "Waiting"),
            (TaskKind.COMMITMENT, "Commitment"),
            (TaskKind.IDEA, "Idea"),
            (TaskKind.REFERENCE, "Reference"),
        ]:
            cls = self._make_classification(kind=kind)
            text = _build_proposal_text("raw", cls, "P")
            assert label_part in text

    def test_next_action_included_when_present(self):
        cls = self._make_classification(next_action="Check fridge first")
        text = _build_proposal_text("raw", cls, "P")
        assert "Check fridge first" in text

    def test_due_hint_included_when_present(self):
        cls = self._make_classification(due_hint="2024-06-15")
        text = _build_proposal_text("raw", cls, "P")
        assert "2024-06-15" in text

    def test_ambiguities_displayed(self):
        cls = self._make_classification(ambiguities=["Which store?", "Budget?"])
        text = _build_proposal_text("raw", cls, "P")
        assert "Which store?" in text
        assert "Budget?" in text
        assert "Ambiguities" in text

    def test_html_escaping_prevents_xss(self):
        # User-provided raw text with HTML tags should be escaped
        cls = self._make_classification(normalized_title="<script>alert(1)</script>")
        text = _build_proposal_text("<b>evil</b>", cls, "P")
        assert "<script>" not in text
        assert "&lt;script&gt;" in text
        assert "&lt;b&gt;evil&lt;/b&gt;" in text

    def test_html_structure(self):
        cls = self._make_classification()
        text = _build_proposal_text("raw", cls, "P")
        assert "<b>" in text  # Uses HTML formatting
        assert "Chiefly detected" in text
