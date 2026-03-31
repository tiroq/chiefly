"""
Unit tests for LLM service: malformed JSON recovery and daily review generation.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from apps.api.services.llm_service import LLMService, _fallback_classification
from apps.api.services.rate_limiter import ProviderRateLimiter, RateLimitDecision
from core.domain.enums import ConfidenceBand, TaskKind
from core.domain.exceptions import RateLimitError
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
        valid_json = json.dumps(
            {
                "kind": "task",
                "normalized_title": "Buy groceries",
                "confidence": "high",
            }
        )
        with patch.object(svc, "_call_llm_sync", return_value=valid_json):
            result = await svc.classify_task("buy groceries", "Available projects:\n- Personal")
        assert result.kind == TaskKind.TASK
        assert result.normalized_title == "Buy groceries"

    @pytest.mark.asyncio
    async def test_json_with_markdown_fences(self):
        svc = self._make_service()
        response = '```json\n{"kind": "waiting", "normalized_title": "Wait for reply"}\n```'
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.classify_task("wait for reply", "Available projects:\n- Personal")
        assert result.kind == TaskKind.WAITING

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back(self):
        svc = self._make_service()
        with patch.object(svc, "_call_llm_sync", return_value="not valid json at all"):
            result = await svc.classify_task("buy groceries", "Available projects:\n- Personal")
        # Should fall back to heuristic classification
        assert result.kind == TaskKind.TASK
        assert result.confidence == ConfidenceBand.LOW

    @pytest.mark.asyncio
    async def test_exception_falls_back(self):
        svc = self._make_service()
        with patch.object(svc, "_call_llm_sync", side_effect=Exception("API down")):
            result = await svc.classify_task("buy groceries", "Available projects:\n- Personal")
        assert result.kind == TaskKind.TASK
        assert result.confidence == ConfidenceBand.LOW

    @pytest.mark.asyncio
    async def test_retries_once_before_fallback(self):
        svc = self._make_service()
        call_count = 0

        def failing_llm(prompt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("oops")

        with patch.object(svc, "_call_llm_sync", side_effect=failing_llm):
            result = await svc.classify_task("some task", "Available projects:\n- Personal")
        assert call_count == 2  # 2 attempts (0 and 1)
        assert result.confidence == ConfidenceBand.LOW

    @pytest.mark.asyncio
    async def test_second_attempt_succeeds(self):
        svc = self._make_service()
        call_count = 0

        def flaky_llm(prompt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("first fail")
            return json.dumps(
                {
                    "kind": "idea",
                    "normalized_title": "New concept",
                    "confidence": "medium",
                }
            )

        with patch.object(svc, "_call_llm_sync", side_effect=flaky_llm):
            result = await svc.classify_task("new concept", "Available projects:\n- Personal")
        assert result.kind == TaskKind.IDEA
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_partial_json_missing_fields_uses_defaults(self):
        svc = self._make_service()
        # Valid JSON but missing optional fields
        response = json.dumps({"kind": "reference", "normalized_title": "API docs"})
        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.classify_task("API documentation", "Available projects:\n- Personal")
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
            result = await svc.classify_task("something", "Available projects:\n- Personal")
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


class TestProviderClientCreation:
    def test_openai_provider_uses_api_key(self):
        with patch("openai.OpenAI") as mock_cls:
            svc = LLMService("openai", "gpt-4o", "sk-test-key")
            svc._get_client()
            mock_cls.assert_called_once_with(api_key="sk-test-key")

    def test_ollama_provider_uses_local_url(self):
        with patch("openai.OpenAI") as mock_cls:
            svc = LLMService("ollama", "qwen3:1.7b", "")
            svc._get_client()
            mock_cls.assert_called_once_with(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
            )

    def test_github_models_provider_uses_github_endpoint(self):
        with patch("openai.OpenAI") as mock_cls:
            svc = LLMService("github_models", "openai/gpt-4o", "ghp_test_pat")
            svc._get_client()
            mock_cls.assert_called_once_with(
                base_url="https://models.github.ai/inference",
                api_key="ghp_test_pat",
            )

    def test_github_models_provider_respects_custom_base_url(self):
        with patch("openai.OpenAI") as mock_cls:
            svc = LLMService(
                "github_models", "openai/gpt-4o", "ghp_test", "https://custom.endpoint"
            )
            svc._get_client()
            mock_cls.assert_called_once_with(
                base_url="https://custom.endpoint",
                api_key="ghp_test",
            )


class TestFromEffectiveConfig:
    def test_creates_service_from_config(self):
        from apps.api.services.model_settings_service import EffectiveLLMConfig

        config = EffectiveLLMConfig(
            provider="github_models",
            model="openai/gpt-4o",
            api_key="ghp_abc",
            base_url="",
            fast_model="openai/gpt-4o-mini",
            quality_model="openai/gpt-4o",
            fallback_model="openai/gpt-4o-mini",
            auto_mode=True,
        )
        svc = LLMService.from_effective_config(config)
        assert svc._provider == "github_models"
        assert svc._model == "openai/gpt-4o"
        assert svc._api_key == "ghp_abc"
        assert svc._fast_model == "openai/gpt-4o-mini"
        assert svc._quality_model == "openai/gpt-4o"
        assert svc._fallback_model == "openai/gpt-4o-mini"
        assert svc._auto_mode is True

    def test_auto_mode_defaults_false(self):
        svc = LLMService("openai", "gpt-4o", "key")
        assert svc._auto_mode is False
        assert svc._fast_model == ""
        assert svc._quality_model == ""
        assert svc._fallback_model == ""


class TestResolveModel:
    def test_returns_primary_when_auto_mode_off(self):
        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
            fast_model="gpt-4o-mini",
            quality_model="gpt-4o",
            auto_mode=False,
        )
        assert svc._resolve_model("fast") == "gpt-4o"
        assert svc._resolve_model("quality") == "gpt-4o"
        assert svc._resolve_model("default") == "gpt-4o"

    def test_routes_fast_when_auto_mode_on(self):
        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
            fast_model="gpt-4o-mini",
            auto_mode=True,
        )
        assert svc._resolve_model("fast") == "gpt-4o-mini"

    def test_routes_quality_when_auto_mode_on(self):
        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
            quality_model="o1-preview",
            auto_mode=True,
        )
        assert svc._resolve_model("quality") == "o1-preview"

    def test_falls_back_to_primary_when_tier_empty(self):
        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
            fast_model="",
            quality_model="",
            auto_mode=True,
        )
        assert svc._resolve_model("fast") == "gpt-4o"
        assert svc._resolve_model("quality") == "gpt-4o"

    def test_default_purpose_always_returns_primary(self):
        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
            fast_model="gpt-4o-mini",
            quality_model="o1-preview",
            auto_mode=True,
        )
        assert svc._resolve_model("default") == "gpt-4o"
        assert svc._resolve_model() == "gpt-4o"


class TestModelOverrideInCallLLM:
    @pytest.mark.asyncio
    async def test_call_and_parse_uses_resolved_model(self):
        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
            fast_model="gpt-4o-mini",
            auto_mode=True,
        )
        import json as _json
        from core.schemas.llm import NormalizationResult

        valid_response = _json.dumps(
            {
                "intent_summary": "test",
                "rewritten_title": "Test task",
                "is_multi_item": False,
                "entities": [],
                "language": "en",
            }
        )

        calls = []

        def capture_call(prompt, step_name="", reqid=None, task_id=None, model_override=""):
            calls.append({"model_override": model_override})
            return valid_response

        with patch.object(svc, "_call_llm_sync", side_effect=capture_call):
            result = await svc.normalize("test task")

        assert result is not None
        assert result.rewritten_title == "Test task"
        assert calls[0]["model_override"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_classify_uses_quality_model(self):
        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
            quality_model="o1-preview",
            auto_mode=True,
        )
        import json as _json
        from core.schemas.llm import ClassifyRouteResult

        valid_response = _json.dumps(
            {
                "type": "task",
                "project": "Personal",
                "title": "Buy groceries",
                "next_action": "Go to store",
                "confidence": "high",
            }
        )

        calls = []

        def capture_call(prompt, step_name="", reqid=None, task_id=None, model_override=""):
            calls.append({"model_override": model_override})
            return valid_response

        with patch.object(svc, "_call_llm_sync", side_effect=capture_call):
            result = await svc.classify_route_title(
                "buy groceries", "buy stuff", "Available projects:\n- Personal"
            )

        assert result is not None
        assert calls[0]["model_override"] == "o1-preview"


class TestFallbackBehavior:
    """Tests for _call_and_parse fallback logic directly (not through normalize,
    which has its own _fallback_normalization wrapper)."""

    @pytest.mark.asyncio
    async def test_fallback_triggered_when_primary_fails(self):
        from core.schemas.llm import NormalizationResult

        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
            fallback_model="gpt-4o-mini",
        )

        valid_response = json.dumps(
            {
                "intent_summary": "Test task",
                "rewritten_title": "Test task",
                "is_multi_item": False,
                "entities": [],
                "language": "en",
            }
        )

        calls = []

        def tracking_call(prompt, step_name="", reqid=None, task_id=None, model_override=""):
            calls.append(model_override)
            if model_override != "gpt-4o-mini":
                raise RuntimeError("primary model failed")
            return valid_response

        with patch.object(svc, "_call_llm_sync", side_effect=tracking_call):
            result = await svc._call_and_parse("test prompt", NormalizationResult, "test_step")

        assert result is not None
        assert result.rewritten_title == "Test task"
        primary_calls = [c for c in calls if c != "gpt-4o-mini"]
        fallback_calls = [c for c in calls if c == "gpt-4o-mini"]
        assert len(primary_calls) >= 1
        assert len(fallback_calls) == 1

    @pytest.mark.asyncio
    async def test_no_fallback_when_primary_succeeds(self):
        from core.schemas.llm import NormalizationResult

        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
            fallback_model="gpt-4o-mini",
        )

        valid_response = json.dumps(
            {
                "intent_summary": "Test task",
                "rewritten_title": "Test task",
                "is_multi_item": False,
                "entities": [],
                "language": "en",
            }
        )

        calls = []

        def tracking_call(prompt, step_name="", reqid=None, task_id=None, model_override=""):
            calls.append(model_override)
            return valid_response

        with patch.object(svc, "_call_llm_sync", side_effect=tracking_call):
            result = await svc._call_and_parse("test prompt", NormalizationResult, "test_step")

        assert result is not None
        fallback_calls = [c for c in calls if c == "gpt-4o-mini"]
        assert len(fallback_calls) == 0

    @pytest.mark.asyncio
    async def test_no_fallback_when_fallback_model_not_set(self):
        from core.schemas.llm import NormalizationResult

        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
        )

        calls = []

        def tracking_call(prompt, step_name="", reqid=None, task_id=None, model_override=""):
            calls.append(model_override)
            raise RuntimeError("always fails")

        with patch.object(svc, "_call_llm_sync", side_effect=tracking_call):
            result = await svc._call_and_parse("test prompt", NormalizationResult, "test_step")

        assert result is None
        assert all(c != "gpt-4o-mini" for c in calls)

    @pytest.mark.asyncio
    async def test_fallback_not_triggered_when_same_as_primary(self):
        from core.schemas.llm import NormalizationResult

        svc = LLMService(
            "openai",
            "gpt-4o",
            "key",
            fallback_model="gpt-4o",
        )

        call_count = 0

        def tracking_call(prompt, step_name="", reqid=None, task_id=None, model_override=""):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("always fails")

        with patch.object(svc, "_call_llm_sync", side_effect=tracking_call):
            result = await svc._call_and_parse("test prompt", NormalizationResult, "test_step")

        assert result is None
        assert call_count == 2


class TestRateLimiterIntegration:
    def _make_service(
        self, provider: str = "openai", rate_limiter: ProviderRateLimiter | None = None
    ) -> LLMService:
        return LLMService(
            provider=provider,
            model="gpt-4o",
            api_key="test-key",
            rate_limiter=rate_limiter,
        )

    def test_call_llm_sync_checks_rate_limiter_allowed(self):
        limiter = ProviderRateLimiter(capacity=10, refill_amount=1, refill_interval=30)
        svc = self._make_service(rate_limiter=limiter)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"result": "ok"}'
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.return_value = mock_client

            result = svc._call_llm_sync("test prompt")

            mock_client.chat.completions.create.assert_called_once()
            assert '{"result": "ok"}' == result

    def test_call_llm_sync_rate_limited_raises(self):
        limiter = ProviderRateLimiter(capacity=1, refill_amount=1, refill_interval=30)
        svc = self._make_service(rate_limiter=limiter)

        with patch("openai.OpenAI"):
            svc._call_llm_sync("first call — consumes the token")

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            with pytest.raises(RateLimitError) as exc_info:
                svc._call_llm_sync("second call — should be denied")

            mock_client.chat.completions.create.assert_not_called()
            assert exc_info.value.provider == "openai"
            assert exc_info.value.retry_after_seconds > 0

    def test_call_llm_sync_no_rate_limiter_proceeds(self):
        svc = self._make_service(rate_limiter=None)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"ok": true}'
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.return_value = mock_client

            result = svc._call_llm_sync("test prompt")
            mock_client.chat.completions.create.assert_called_once()

    def test_call_llm_sync_ollama_bypasses_rate_limiter(self):
        limiter = ProviderRateLimiter(capacity=1, refill_amount=1, refill_interval=30)
        svc = self._make_service(provider="ollama", rate_limiter=limiter)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"ok": true}'
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.return_value = mock_client

            for _ in range(5):
                svc._call_llm_sync("test prompt")

            assert mock_client.chat.completions.create.call_count == 5

    def test_rate_limit_error_has_correct_fields(self):
        limiter = ProviderRateLimiter(capacity=1, refill_amount=1, refill_interval=30)
        svc = self._make_service(provider="github_models", rate_limiter=limiter)

        with patch("openai.OpenAI"):
            svc._call_llm_sync("consume token")

        with patch("openai.OpenAI"):
            with pytest.raises(RateLimitError) as exc_info:
                svc._call_llm_sync("denied")

            err = exc_info.value
            assert err.provider == "github_models"
            assert err.retry_after_seconds > 0
            assert "github_models" in str(err)

    def test_rate_limiter_called_with_correct_provider(self):
        limiter = MagicMock(spec=ProviderRateLimiter)
        limiter.check.return_value = RateLimitDecision(
            allowed=True, tokens_remaining=9, retry_after_seconds=0.0
        )
        svc = self._make_service(provider="github_models", rate_limiter=limiter)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"ok": true}'
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.return_value = mock_client

            svc._call_llm_sync("test prompt")

        limiter.check.assert_called_once_with("github_models")


class TestRateLimitErrorPropagation:
    def _make_service(self) -> LLMService:
        return LLMService(
            provider="openai",
            model="gpt-4o",
            api_key="test-key",
        )

    @pytest.mark.asyncio
    async def test_try_call_and_parse_propagates_rate_limit_error(self):
        svc = self._make_service()
        with patch.object(
            svc,
            "_call_llm_sync",
            side_effect=RateLimitError(provider="openai", retry_after_seconds=30.0),
        ):
            with pytest.raises(RateLimitError) as exc_info:
                from core.schemas.llm import NormalizationResult

                await svc._try_call_and_parse("prompt", NormalizationResult, "test_step", retries=2)
            assert exc_info.value.provider == "openai"

    @pytest.mark.asyncio
    async def test_call_and_parse_propagates_rate_limit_error(self):
        svc = self._make_service()
        with patch.object(
            svc,
            "_call_llm_sync",
            side_effect=RateLimitError(provider="openai", retry_after_seconds=30.0),
        ):
            with pytest.raises(RateLimitError):
                from core.schemas.llm import NormalizationResult

                await svc._call_and_parse("prompt", NormalizationResult, "test_step")

    @pytest.mark.asyncio
    async def test_classify_task_propagates_rate_limit_error(self):
        svc = self._make_service()
        with patch.object(
            svc,
            "_call_llm_sync",
            side_effect=RateLimitError(provider="openai", retry_after_seconds=30.0),
        ):
            with pytest.raises(RateLimitError):
                await svc.classify_task("buy groceries", "Available projects:\n- Personal")

    @pytest.mark.asyncio
    async def test_run_pipeline_propagates_rate_limit_error(self):
        svc = self._make_service()
        with patch.object(
            svc,
            "_call_llm_sync",
            side_effect=RateLimitError(provider="openai", retry_after_seconds=30.0),
        ):
            with pytest.raises(RateLimitError):
                await svc.run_pipeline(
                    raw_text="buy groceries",
                    project_context="Available projects:\n- Personal",
                )

    @pytest.mark.asyncio
    async def test_generate_project_description_propagates_rate_limit_error(self):
        svc = self._make_service()
        with patch.object(
            svc,
            "_call_llm_sync",
            side_effect=RateLimitError(provider="openai", retry_after_seconds=30.0),
        ):
            with pytest.raises(RateLimitError):
                await svc.generate_project_description("TestProject", ["task1"])

    @pytest.mark.asyncio
    async def test_rewrite_title_propagates_rate_limit_error(self):
        svc = self._make_service()
        with patch.object(
            svc,
            "_call_llm_sync",
            side_effect=RateLimitError(provider="openai", retry_after_seconds=30.0),
        ):
            with pytest.raises(RateLimitError):
                await svc.rewrite_title("some raw text")

    @pytest.mark.asyncio
    async def test_generate_draft_message_propagates_rate_limit_error(self):
        svc = self._make_service()
        with patch.object(
            svc,
            "_call_llm_sync",
            side_effect=RateLimitError(provider="openai", retry_after_seconds=30.0),
        ):
            with pytest.raises(RateLimitError):
                await svc.generate_draft_message("Task title", "task")

    @pytest.mark.asyncio
    async def test_non_rate_limit_exception_still_handled_gracefully(self):
        svc = self._make_service()
        with patch.object(
            svc,
            "_call_llm_sync",
            side_effect=ValueError("connection error"),
        ):
            result = await svc.classify_task("buy groceries", "Available projects:\n- Personal")
            assert result.kind == TaskKind.TASK
            assert result.normalized_title == "buy groceries"
