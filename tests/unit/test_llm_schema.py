"""
Unit tests for LLM schema validation.
"""

import pytest
from pydantic import ValidationError

from core.domain.enums import ConfidenceBand, TaskKind
from core.schemas.llm import TaskClassificationResult


class TestTaskClassificationResult:
    def test_valid_full_schema(self):
        data = {
            "kind": "task",
            "normalized_title": "Buy groceries",
            "project_guess": "Personal",
            "project_confidence": "high",
            "next_action": "Make a shopping list",
            "due_hint": "2024-06-15",
            "substeps": ["List items", "Check fridge"],
            "confidence": "high",
            "ambiguities": [],
            "notes_for_user": None,
            "internal_rationale": "Clearly a personal errand task.",
        }
        result = TaskClassificationResult.model_validate(data)
        assert result.kind == TaskKind.TASK
        assert result.normalized_title == "Buy groceries"
        assert result.confidence == ConfidenceBand.HIGH
        assert len(result.substeps) == 2

    def test_minimal_schema(self):
        data = {"kind": "idea", "normalized_title": "New app concept"}
        result = TaskClassificationResult.model_validate(data)
        assert result.kind == TaskKind.IDEA
        assert result.substeps == []
        assert result.ambiguities == []
        assert result.confidence == ConfidenceBand.MEDIUM

    def test_title_strip_whitespace(self):
        data = {"kind": "task", "normalized_title": "  Buy groceries  "}
        result = TaskClassificationResult.model_validate(data)
        assert result.normalized_title == "Buy groceries"

    def test_invalid_kind(self):
        data = {"kind": "invalid_kind", "normalized_title": "Test"}
        with pytest.raises(ValidationError):
            TaskClassificationResult.model_validate(data)

    def test_empty_title_fails(self):
        data = {"kind": "task", "normalized_title": ""}
        with pytest.raises(ValidationError):
            TaskClassificationResult.model_validate(data)

    def test_waiting_kind(self):
        data = {
            "kind": "waiting",
            "normalized_title": "Wait for Alex to send certificates",
            "confidence": "high",
        }
        result = TaskClassificationResult.model_validate(data)
        assert result.kind == TaskKind.WAITING

    def test_commitment_kind(self):
        data = {
            "kind": "commitment",
            "normalized_title": "Send report to client by Friday",
            "confidence": "medium",
        }
        result = TaskClassificationResult.model_validate(data)
        assert result.kind == TaskKind.COMMITMENT

    def test_substeps_none_becomes_empty_list(self):
        data = {
            "kind": "task",
            "normalized_title": "Some task",
            "substeps": None,
        }
        result = TaskClassificationResult.model_validate(data)
        assert result.substeps == []

    def test_ambiguities_none_becomes_empty_list(self):
        data = {
            "kind": "task",
            "normalized_title": "Some task",
            "ambiguities": None,
        }
        result = TaskClassificationResult.model_validate(data)
        assert result.ambiguities == []

    def test_all_valid_kinds(self):
        for kind_value in ("task", "waiting", "commitment", "idea", "reference"):
            data = {"kind": kind_value, "normalized_title": f"Test {kind_value}"}
            result = TaskClassificationResult.model_validate(data)
            assert result.kind.value == kind_value

    def test_all_confidence_bands(self):
        for band in ("low", "medium", "high"):
            data = {
                "kind": "task",
                "normalized_title": "Test",
                "confidence": band,
            }
            result = TaskClassificationResult.model_validate(data)
            assert result.confidence.value == band
