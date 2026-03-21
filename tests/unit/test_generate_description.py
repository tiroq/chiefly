import json
from unittest.mock import patch

import pytest

from apps.api.services.llm_service import LLMService


class TestGenerateProjectDescription:
    def _make_service(self) -> LLMService:
        return LLMService(
            provider="openai",
            model="gpt-4o",
            api_key="test-key",
        )

    @pytest.mark.asyncio
    async def test_successful_generation_returns_expected_fields(self):
        svc = self._make_service()
        response = json.dumps(
            {
                "description": "Work related to API integrations and data sync.",
                "aliases": ["integrations", "sync"],
                "keywords": ["api", "webhook"],
                "example_patterns": ["connect service A to service B"],
            }
        )

        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.generate_project_description(
                "Integrations",
                ["Set up webhook", "Map external API fields"],
            )

        assert result["description"] == "Work related to API integrations and data sync."
        assert result["aliases"] == ["integrations", "sync"]
        assert result["keywords"] == ["api", "webhook"]
        assert result["example_patterns"] == ["connect service A to service B"]
        assert isinstance(result["description"], str)
        assert isinstance(result["aliases"], list)
        assert isinstance(result["keywords"], list)
        assert isinstance(result["example_patterns"], list)

    @pytest.mark.asyncio
    async def test_parses_json_wrapped_in_markdown_code_fences(self):
        svc = self._make_service()
        response = """```json
{"description": "Ops tasks", "aliases": ["operations"], "keywords": ["infra"], "example_patterns": ["deploy service"]}
```"""

        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.generate_project_description("Ops", ["Deploy to staging"])

        assert result["description"] == "Ops tasks"
        assert result["aliases"] == ["operations"]
        assert result["keywords"] == ["infra"]
        assert result["example_patterns"] == ["deploy service"]

    @pytest.mark.asyncio
    async def test_invalid_json_first_attempt_then_valid_on_retry(self):
        svc = self._make_service()
        valid_response = json.dumps(
            {
                "description": "Client delivery work",
                "aliases": ["delivery"],
                "keywords": ["client"],
                "example_patterns": ["send draft to client"],
            }
        )

        with patch.object(
            svc,
            "_call_llm_sync",
            side_effect=["{not valid json", valid_response],
        ) as mocked_call:
            result = await svc.generate_project_description("Client Work", ["Send weekly report"])

        assert mocked_call.call_count == 2
        assert result["description"] == "Client delivery work"

    @pytest.mark.asyncio
    async def test_failure_on_both_attempts_returns_fallback(self):
        svc = self._make_service()

        with patch.object(
            svc, "_call_llm_sync", side_effect=Exception("LLM unavailable")
        ) as mocked_call:
            result = await svc.generate_project_description("Project X", ["Task one"])

        assert mocked_call.call_count == 2
        assert result == {
            "description": "Tasks related to Project X",
            "aliases": [],
            "keywords": [],
            "example_patterns": [],
        }

    @pytest.mark.asyncio
    async def test_uses_only_first_20_tasks_in_prompt(self):
        svc = self._make_service()
        sample_tasks = [f"task {idx}" for idx in range(1, 26)]
        captured_prompts: list[str] = []

        def capture_prompt(prompt: str) -> str:
            captured_prompts.append(prompt)
            return json.dumps(
                {
                    "description": "Batch work",
                    "aliases": [],
                    "keywords": [],
                    "example_patterns": [],
                }
            )

        with patch.object(svc, "_call_llm_sync", side_effect=capture_prompt):
            _ = await svc.generate_project_description("Batch", sample_tasks)

        assert captured_prompts
        prompt = captured_prompts[0]
        assert "- task 1" in prompt
        assert "- task 20" in prompt
        assert "- task 21" not in prompt
        assert "- task 25" not in prompt

    @pytest.mark.asyncio
    async def test_invalid_field_types_are_normalized_to_expected_return_types(self):
        svc = self._make_service()
        response = json.dumps(
            {
                "description": 123,
                "aliases": "not-a-list",
                "keywords": {"k": "v"},
                "example_patterns": None,
            }
        )

        with patch.object(svc, "_call_llm_sync", return_value=response):
            result = await svc.generate_project_description("Validation", ["Task"])

        assert result["description"] == ""
        assert result["aliases"] == []
        assert result["keywords"] == []
        assert result["example_patterns"] == []
        assert isinstance(result["description"], str)
        assert isinstance(result["aliases"], list)
        assert isinstance(result["keywords"], list)
        assert isinstance(result["example_patterns"], list)
