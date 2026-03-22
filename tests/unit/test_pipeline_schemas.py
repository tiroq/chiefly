import pytest
from pydantic import ValidationError

from core.domain.enums import ConfidenceBand, TaskKind
from core.schemas.llm import (
    AmbiguityOption,
    ClassifyRouteResult,
    DescriptionResult,
    DisambiguationResult,
    NormalizationResult,
    PipelineResult,
    StepsResult,
)


class TestNormalizationResult:
    def test_valid_full(self):
        data = {
            "intent_summary": "Buy groceries from the store",
            "is_multi_item": False,
            "entities": ["store", "groceries"],
            "language": "en",
        }
        result = NormalizationResult.model_validate(data)
        assert result.intent_summary == "Buy groceries from the store"
        assert result.is_multi_item is False
        assert result.entities == ["store", "groceries"]
        assert result.language == "en"

    def test_minimal(self):
        data = {"intent_summary": "Do something"}
        result = NormalizationResult.model_validate(data)
        assert result.is_multi_item is False
        assert result.entities == []
        assert result.language == "en"

    def test_strips_whitespace(self):
        data = {"intent_summary": "  trimmed  "}
        result = NormalizationResult.model_validate(data)
        assert result.intent_summary == "trimmed"

    def test_empty_intent_fails(self):
        with pytest.raises(ValidationError):
            NormalizationResult.model_validate({"intent_summary": ""})

    def test_invalid_language_fails(self):
        with pytest.raises(ValidationError):
            NormalizationResult.model_validate({"intent_summary": "test", "language": "fr"})

    def test_valid_languages(self):
        for lang in ("en", "ru", "mixed"):
            result = NormalizationResult.model_validate(
                {"intent_summary": "test", "language": lang}
            )
            assert result.language == lang

    def test_entities_none_becomes_empty(self):
        result = NormalizationResult.model_validate({"intent_summary": "test", "entities": None})
        assert result.entities == []

    def test_multi_item_true(self):
        result = NormalizationResult.model_validate(
            {"intent_summary": "two tasks", "is_multi_item": True}
        )
        assert result.is_multi_item is True


class TestClassifyRouteResult:
    def test_valid_full(self):
        data = {
            "type": "task",
            "project": "Personal",
            "confidence": "high",
            "reasoning": "Clearly a personal task",
            "title": "Buy groceries from store",
            "next_action": "Make a shopping list",
            "due_hint": "2024-06-15",
        }
        result = ClassifyRouteResult.model_validate(data)
        assert result.type == TaskKind.TASK
        assert result.project == "Personal"
        assert result.confidence == ConfidenceBand.HIGH
        assert result.title == "Buy groceries from store"
        assert result.next_action == "Make a shopping list"

    def test_minimal(self):
        data = {"type": "idea", "project": "Writing", "title": "New concept"}
        result = ClassifyRouteResult.model_validate(data)
        assert result.confidence == ConfidenceBand.MEDIUM
        assert result.reasoning == ""
        assert result.next_action == ""
        assert result.due_hint is None

    def test_all_task_types(self):
        for kind in ("task", "waiting", "commitment", "idea", "reference"):
            data = {"type": kind, "project": "P", "title": f"Test {kind}"}
            result = ClassifyRouteResult.model_validate(data)
            assert result.type.value == kind

    def test_invalid_type_fails(self):
        with pytest.raises(ValidationError):
            ClassifyRouteResult.model_validate({"type": "invalid", "project": "P", "title": "T"})

    def test_empty_project_fails(self):
        with pytest.raises(ValidationError):
            ClassifyRouteResult.model_validate({"type": "task", "project": "", "title": "T"})

    def test_empty_title_fails(self):
        with pytest.raises(ValidationError):
            ClassifyRouteResult.model_validate({"type": "task", "project": "P", "title": ""})

    def test_title_truncated(self):
        long_title = "x" * 300
        data = {"type": "task", "project": "P", "title": long_title}
        result = ClassifyRouteResult.model_validate(data)
        assert len(result.title) <= 200

    def test_strips_whitespace(self):
        data = {
            "type": "task",
            "project": "  Personal  ",
            "title": "  Buy milk  ",
            "next_action": "  Go to store  ",
            "reasoning": "  Some reason  ",
        }
        result = ClassifyRouteResult.model_validate(data)
        assert result.project == "Personal"
        assert result.title == "Buy milk"
        assert result.next_action == "Go to store"
        assert result.reasoning == "Some reason"


class TestDescriptionResult:
    def test_valid(self):
        result = DescriptionResult.model_validate(
            {"description": "This task involves buying items from the store."}
        )
        assert "buying items" in result.description

    def test_empty_fails(self):
        with pytest.raises(ValidationError):
            DescriptionResult.model_validate({"description": ""})

    def test_strips_whitespace(self):
        result = DescriptionResult.model_validate({"description": "  trimmed  "})
        assert result.description == "trimmed"

    def test_truncates_long(self):
        long_desc = "x" * 1500
        result = DescriptionResult.model_validate({"description": long_desc})
        assert len(result.description) <= 1000


class TestStepsResult:
    def test_valid(self):
        result = StepsResult.model_validate({"steps": ["Step 1", "Step 2", "Step 3"]})
        assert len(result.steps) == 3

    def test_none_becomes_empty(self):
        result = StepsResult.model_validate({"steps": None})
        assert result.steps == []

    def test_strips_step_whitespace(self):
        result = StepsResult.model_validate({"steps": ["  Step 1  ", "  Step 2  "]})
        assert result.steps == ["Step 1", "Step 2"]

    def test_filters_empty_steps(self):
        result = StepsResult.model_validate({"steps": ["Step 1", "", "Step 3"]})
        assert "" not in result.steps

    def test_truncates_to_ten(self):
        many_steps = [f"Step {i}" for i in range(15)]
        result = StepsResult.model_validate({"steps": many_steps})
        assert len(result.steps) <= 10


class TestAmbiguityOption:
    def test_valid(self):
        data = {
            "type": "task",
            "title": "Do something specific",
            "reason": "Because it seems actionable",
        }
        result = AmbiguityOption.model_validate(data)
        assert result.type == TaskKind.TASK
        assert result.title == "Do something specific"

    def test_empty_title_fails(self):
        with pytest.raises(ValidationError):
            AmbiguityOption.model_validate({"type": "task", "title": "", "reason": "r"})


class TestDisambiguationResult:
    def test_valid(self):
        data = {
            "options": [
                {"type": "task", "title": "Option A", "reason": "Reason A"},
                {"type": "idea", "title": "Option B", "reason": "Reason B"},
            ]
        }
        result = DisambiguationResult.model_validate(data)
        assert len(result.options) == 2

    def test_empty_options_fails(self):
        with pytest.raises(ValidationError):
            DisambiguationResult.model_validate({"options": []})


class TestPipelineResult:
    def test_valid_full(self):
        result = PipelineResult(
            type=TaskKind.TASK,
            project="Personal",
            title="Buy groceries",
            next_action="Make list",
            confidence=ConfidenceBand.HIGH,
            intent_summary="Need to buy food",
            language="en",
            description="Weekly grocery shopping",
            steps=["Make list", "Go to store", "Buy items"],
        )
        assert result.type == TaskKind.TASK
        assert result.project == "Personal"
        assert len(result.steps) == 3

    def test_minimal(self):
        result = PipelineResult(
            type=TaskKind.IDEA,
            project="Writing",
            title="New concept",
        )
        assert result.next_action == ""
        assert result.confidence == ConfidenceBand.MEDIUM
        assert result.description is None
        assert result.steps == []
        assert result.disambiguation_options == []

    def test_to_legacy_maps_fields(self):
        result = PipelineResult(
            type=TaskKind.WAITING,
            project="NFT Gateway",
            title="Wait for certificates",
            next_action="Send follow-up",
            confidence=ConfidenceBand.HIGH,
            description="Waiting on Alex",
            steps=["Send message", "Wait for reply"],
            due_hint="2024-06-15",
            reasoning="Contains waiting keyword",
        )
        legacy = result.to_legacy()
        assert legacy.kind == TaskKind.WAITING
        assert legacy.normalized_title == "Wait for certificates"
        assert legacy.project_guess == "NFT Gateway"
        assert legacy.project_confidence == ConfidenceBand.HIGH
        assert legacy.next_action == "Send follow-up"
        assert legacy.due_hint == "2024-06-15"
        assert legacy.substeps == ["Send message", "Wait for reply"]
        assert legacy.confidence == ConfidenceBand.HIGH
        assert legacy.notes_for_user == "Waiting on Alex"
        assert legacy.internal_rationale == "Contains waiting keyword"

    def test_to_legacy_empty_next_action_becomes_none(self):
        result = PipelineResult(
            type=TaskKind.REFERENCE,
            project="Personal",
            title="API docs",
            next_action="",
        )
        legacy = result.to_legacy()
        assert legacy.next_action is None

    def test_to_legacy_preserves_all_kinds(self):
        for kind in TaskKind:
            result = PipelineResult(
                type=kind,
                project="P",
                title=f"Test {kind.value}",
            )
            legacy = result.to_legacy()
            assert legacy.kind == kind
