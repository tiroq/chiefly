"""
Unit tests for LLM service: malformed JSON recovery and daily review generation.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from apps.api.services.llm_service import LLMService, _fallback_classification
from core.domain.enums import ConfidenceBand, TaskKind
from core.schemas.llm import TaskClassificationResult


class TestLLMServiceClassify:
    """Tests for LLMService.classify_task handling malformed responses."""

    def _make_service(self) -> LLMService:
        return LLMService(
            provider="openai",
            model="gpt-4o",
            api_key="test-key",
        )

    @pytest.mark.asyncio
    async def test_valid_json_response(self):
        svc = self._make_service()
        valid_json = json.dumps({
            "kind": "task",
            "normalized_title": "Buy groceries",
            "confidence": "high",
        })
        with patch.object(svc, "_call_llm_sync", return_value=valid_json):
            result = await svc.classify_task("buy groceries", ["Personal"])
        assert result.kind == TaskKind.TASK
        assert result.normalized_title == "Buy groceries"

    @pytest.mark.asyncio
    async def test_json_with_markdown_fences(self):
        svc = self._make_service()
        response = '```json\n{"kind": "waiting", "normalized_title": "Wait for reply"}\n```'
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.classify_task("wait for reply", ["Personal"])
        assert result.kind == TaskKind.WAITING

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back(self):
        svc = self._make_service()
        with patch.object(svc, "_call_llm_sync", return_value="not valid json at all"):
            result = await svc.classify_task("buy groceries", ["Personal"])
        # Should fall back to heuristic classification
        assert result.kind == TaskKind.TASK
        assert result.confidence == ConfidenceBand.LOW

    @pytest.mark.asyncio
    async def test_exception_falls_back(self):
        svc = self._make_service()
        with patch.object(svc, "_call_llm_sync", side_effect=Exception("API down")):
            result = await svc.classify_task("buy groceries", ["Personal"])
        assert result.kind == TaskKind.TASK
        assert result.confidence == ConfidenceBand.LOW

    @pytest.mark.asyncio
    async def test_retries_once_before_fallback(self):
        svc = self._make_service()
        call_count = 0

        def failing_llm(prompt):
            nonlocal call_count
            call_count += 1
            raise Exception("oops")

        with patch.object(svc, "_call_llm_sync", side_effect=failing_llm):
            result = await svc.classify_task("some task", [])
        assert call_count == 2  # 2 attempts (0 and 1)
        assert result.confidence == ConfidenceBand.LOW

    @pytest.mark.asyncio
    async def test_second_attempt_succeeds(self):
        svc = self._make_service()
        call_count = 0

        def flaky_llm(prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("first fail")
            return json.dumps({
                "kind": "idea",
                "normalized_title": "New concept",
                "confidence": "medium",
            })

        with patch.object(svc, "_call_llm_sync", side_effect=flaky_llm):
            result = await svc.classify_task("new concept", [])
        assert result.kind == TaskKind.IDEA
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_partial_json_missing_fields_uses_defaults(self):
        svc = self._make_service()
        # Valid JSON but missing optional fields
        response = json.dumps({"kind": "reference", "normalized_title": "API docs"})
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.classify_task("API documentation", [])
        assert result.kind == TaskKind.REFERENCE
        assert result.substeps == []
        assert result.ambiguities == []
        assert result.confidence == ConfidenceBand.MEDIUM  # Default

    @pytest.mark.asyncio
    async def test_completely_invalid_schema_falls_back(self):
        svc = self._make_service()
        # Valid JSON but wrong schema (missing required 'kind')
        response = json.dumps({"title": "something", "type": "task"})
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.classify_task("something", [])
        assert result.confidence == ConfidenceBand.LOW


class TestDailyReviewGeneration:
    def test_generates_text_with_sections(self):
        svc = LLMService("openai", "gpt-4o", "key")
        payload = {
            "active_tasks": [{"title": "Task A"}, {"title": "Task B"}],
            "waiting_items": [{"title": "Wait C"}],
            "stale_tasks": [{"title": "Stale D"}],
        }
        result = svc.generate_daily_review(payload)
        assert "Task A" in result
        assert "Task B" in result
        assert "Wait C" in result
        assert "Stale D" in result
        assert "Active tasks (2)" in result
        assert "Waiting items (1)" in result
        assert "Stale tasks (1)" in result

    def test_empty_payload(self):
        svc = LLMService("openai", "gpt-4o", "key")
        result = svc.generate_daily_review({})
        assert "daily task summary" in result.lower()

    def test_missing_sections_handled(self):
        svc = LLMService("openai", "gpt-4o", "key")
        payload = {"active_tasks": [{"title": "Only this"}]}
        result = svc.generate_daily_review(payload)
        assert "Only this" in result
        assert "Waiting" not in result
        assert "Stale" not in result
