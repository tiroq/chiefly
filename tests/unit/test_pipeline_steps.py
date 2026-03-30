import json
from unittest.mock import patch

import pytest

from apps.api.services.llm_service import (
    LLMService,
    _fallback_normalization,
    _fallback_pipeline,
)
from core.domain.enums import ConfidenceBand, TaskKind


def _make_service() -> LLMService:
    return LLMService(provider="openai", model="gpt-4o", api_key="test-key")


class TestNormalizeStep:
    @pytest.mark.asyncio
    async def test_valid_response(self):
        svc = _make_service()
        response = json.dumps(
            {
                "intent_summary": "Buy groceries for dinner",
                "is_multi_item": False,
                "entities": ["groceries"],
                "language": "en",
            }
        )
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.normalize("купить продукты на ужин")
        assert result.intent_summary == "Buy groceries for dinner"
        assert result.language == "en"

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        svc = _make_service()
        with patch.object(svc, "_call_llm_sync", side_effect=Exception("API down")):
            result = await svc.normalize("some text")
        assert result.intent_summary == "some text"
        assert result.language == "en"

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self):
        svc = _make_service()
        with patch.object(svc, "_call_llm_sync", return_value="not json"):
            result = await svc.normalize("some text")
        assert result.intent_summary == "some text"

    @pytest.mark.asyncio
    async def test_multi_item_detection(self):
        svc = _make_service()
        response = json.dumps(
            {
                "intent_summary": "Two tasks combined",
                "is_multi_item": True,
                "entities": [],
                "language": "mixed",
            }
        )
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.normalize("buy milk and call dentist")
        assert result.is_multi_item is True
        assert result.language == "mixed"


class TestClassifyRouteTitleStep:
    @pytest.mark.asyncio
    async def test_valid_response(self):
        svc = _make_service()
        response = json.dumps(
            {
                "type": "task",
                "project": "Personal",
                "confidence": "high",
                "reasoning": "Personal errand",
                "title": "Buy groceries from store",
                "next_action": "Make a shopping list",
            }
        )
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.classify_route_title(
                raw_text="buy groceries",
                intent_summary="Buy groceries",
                project_context="Available projects:\n- Personal",
            )
        assert result is not None
        assert result.type == TaskKind.TASK
        assert result.project == "Personal"
        assert result.title == "Buy groceries from store"

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self):
        svc = _make_service()
        with patch.object(svc, "_call_llm_sync", side_effect=Exception("fail")):
            result = await svc.classify_route_title(
                raw_text="x", intent_summary="x", project_context="p"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_custom_instructions_appended(self):
        svc = _make_service()
        captured_prompts = []

        def capture_prompt(prompt, *args, **kwargs):
            captured_prompts.append(prompt)
            return json.dumps(
                {
                    "type": "task",
                    "project": "P",
                    "title": "T",
                    "confidence": "high",
                    "reasoning": "r",
                    "next_action": "n",
                }
            )

        with patch.object(svc, "_call_llm_sync", side_effect=capture_prompt):
            await svc.classify_route_title(
                raw_text="x",
                intent_summary="x",
                project_context="p",
                custom_instructions="Always classify as waiting",
            )
        assert "Always classify as waiting" in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_retries_once(self):
        svc = _make_service()
        call_count = 0

        def flaky(prompt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("first fail")
            return json.dumps(
                {
                    "type": "idea",
                    "project": "P",
                    "title": "T",
                    "confidence": "low",
                    "reasoning": "r",
                    "next_action": "n",
                }
            )

        with patch.object(svc, "_call_llm_sync", side_effect=flaky):
            result = await svc.classify_route_title(
                raw_text="x", intent_summary="x", project_context="p"
            )
        assert result is not None
        assert result.type == TaskKind.IDEA
        assert call_count == 2


class TestGenerateDescriptionStep:
    @pytest.mark.asyncio
    async def test_valid_response(self):
        svc = _make_service()
        response = json.dumps({"description": "Weekly grocery shopping task."})
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.generate_description("buy groceries", "Buy groceries")
        assert result is not None
        assert "grocery" in result.description.lower()

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self):
        svc = _make_service()
        with patch.object(svc, "_call_llm_sync", side_effect=Exception("fail")):
            result = await svc.generate_description("x", "T")
        assert result is None


class TestGenerateStepsStep:
    @pytest.mark.asyncio
    async def test_valid_response(self):
        svc = _make_service()
        response = json.dumps({"steps": ["Step 1", "Step 2", "Step 3"]})
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.generate_steps("Buy groceries", "Make list")
        assert result is not None
        assert len(result.steps) == 3

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self):
        svc = _make_service()
        with patch.object(svc, "_call_llm_sync", side_effect=Exception("fail")):
            result = await svc.generate_steps("T", "N")
        assert result is None


class TestDisambiguateStep:
    @pytest.mark.asyncio
    async def test_valid_response(self):
        svc = _make_service()
        response = json.dumps(
            {
                "options": [
                    {"type": "task", "title": "Option A", "reason": "R1"},
                    {"type": "idea", "title": "Option B", "reason": "R2"},
                ]
            }
        )
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.disambiguate("ambiguous text", "unclear intent")
        assert result is not None
        assert len(result.options) == 2

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self):
        svc = _make_service()
        with patch.object(svc, "_call_llm_sync", side_effect=Exception("fail")):
            result = await svc.disambiguate("x", "x")
        assert result is None


class TestFallbackFunctions:
    def test_fallback_normalization(self):
        result = _fallback_normalization("some raw text")
        assert result.intent_summary == "some raw text"
        assert result.language == "en"
        assert result.is_multi_item is False

    def test_fallback_normalization_empty(self):
        result = _fallback_normalization("")
        assert result.intent_summary == "unknown"

    def test_fallback_normalization_truncates(self):
        result = _fallback_normalization("x" * 600)
        assert len(result.intent_summary) <= 500

    def test_fallback_pipeline(self):
        result = _fallback_pipeline("buy milk", "Personal")
        assert result.type == TaskKind.TASK
        assert result.project == "Personal"
        assert result.confidence == ConfidenceBand.LOW

    def test_fallback_pipeline_waiting(self):
        result = _fallback_pipeline("жду от alex сертификаты")
        assert result.type == TaskKind.WAITING


class TestRunPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_happy_path(self):
        svc = _make_service()
        call_count = 0

        def mock_llm(prompt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps(
                    {
                        "intent_summary": "Buy groceries",
                        "is_multi_item": False,
                        "entities": ["groceries"],
                        "language": "en",
                    }
                )
            elif call_count == 2:
                return json.dumps(
                    {
                        "type": "task",
                        "project": "Personal",
                        "confidence": "high",
                        "reasoning": "Personal errand",
                        "title": "Buy groceries from store",
                        "next_action": "Make a shopping list",
                    }
                )
            # call_count == 3: description step (always runs)
            return json.dumps({"description": "auto-generated"})

        with patch.object(svc, "_call_llm_sync", side_effect=mock_llm):
            result = await svc.run_pipeline(
                raw_text="купить продукты",
                project_context="Available projects:\n- Personal",
            )
        assert result.type == TaskKind.TASK
        assert result.project == "Personal"
        assert result.title == "Buy groceries from store"
        assert result.intent_summary == "Buy groceries"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_pipeline_with_description_and_steps(self):
        svc = _make_service()
        call_count = 0

        def mock_llm(prompt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps(
                    {
                        "intent_summary": "Buy groceries",
                        "is_multi_item": False,
                        "entities": [],
                        "language": "en",
                    }
                )
            elif call_count == 2:
                return json.dumps(
                    {
                        "type": "task",
                        "project": "Personal",
                        "confidence": "high",
                        "reasoning": "r",
                        "title": "Buy groceries",
                        "next_action": "Make list",
                    }
                )
            elif call_count == 3:
                return json.dumps({"description": "Weekly shopping"})
            elif call_count == 4:
                return json.dumps({"steps": ["List items", "Go to store"]})
            return "{}"

        with patch.object(svc, "_call_llm_sync", side_effect=mock_llm):
            result = await svc.run_pipeline(
                raw_text="buy groceries",
                project_context="p",
                include_description=True,
                include_steps=True,
            )
        assert result.description == "Weekly shopping"
        assert result.steps == ["List items", "Go to store"]
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_pipeline_low_confidence_triggers_disambiguation(self):
        svc = _make_service()
        call_count = 0

        def mock_llm(prompt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps(
                    {
                        "intent_summary": "Ambiguous text",
                        "is_multi_item": False,
                        "entities": [],
                        "language": "en",
                    }
                )
            elif call_count == 2:
                return json.dumps(
                    {
                        "type": "task",
                        "project": "Personal",
                        "confidence": "low",
                        "reasoning": "unclear",
                        "title": "Ambiguous thing",
                        "next_action": "Clarify",
                    }
                )
            elif call_count == 3:
                return json.dumps(
                    {
                        "options": [
                            {"type": "task", "title": "Option A", "reason": "R1"},
                            {"type": "idea", "title": "Option B", "reason": "R2"},
                        ]
                    }
                )
            # call 4: description step (always runs)
            return json.dumps({"description": "auto-generated"})

        with patch.object(svc, "_call_llm_sync", side_effect=mock_llm):
            result = await svc.run_pipeline(
                raw_text="something ambiguous",
                project_context="p",
            )
        assert result.confidence == ConfidenceBand.LOW
        assert len(result.disambiguation_options) == 2
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_pipeline_classify_failure_returns_fallback(self):
        svc = _make_service()
        call_count = 0

        def mock_llm(prompt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return json.dumps(
                    {
                        "intent_summary": "Some intent",
                        "is_multi_item": False,
                        "entities": [],
                        "language": "en",
                    }
                )
            raise Exception("classify failed")

        with patch.object(svc, "_call_llm_sync", side_effect=mock_llm):
            result = await svc.run_pipeline(
                raw_text="buy milk",
                project_context="p",
            )
        assert result.confidence == ConfidenceBand.LOW
        assert result.type == TaskKind.TASK

    @pytest.mark.asyncio
    async def test_pipeline_total_failure_returns_fallback(self):
        svc = _make_service()
        with patch.object(svc, "_call_llm_sync", side_effect=Exception("all fail")):
            result = await svc.run_pipeline(
                raw_text="buy milk",
                project_context="p",
            )
        assert result.confidence == ConfidenceBand.LOW
        assert result.type == TaskKind.TASK
        assert result.project == "Personal"
