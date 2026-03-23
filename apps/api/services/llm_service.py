from __future__ import annotations

import json
import asyncio
from typing import TypeVar

from pydantic import BaseModel

from apps.api.logging import get_logger
from apps.api.prompts.pipeline import (
    CLASSIFY_ROUTE_TITLE,
    DESCRIPTION,
    DISAMBIGUATE,
    NORMALIZE,
    STEPS,
)
from core.domain.enums import ConfidenceBand, TaskKind
from core.schemas.llm import (
    ClassifyRouteResult,
    DescriptionResult,
    DisambiguationResult,
    NormalizationResult,
    PipelineResult,
    StepsResult,
    TaskClassificationResult,
)

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_CLASSIFY_PROMPT_TEMPLATE = """
You are Chiefly, an AI Chief of Staff. Analyze the following raw task text and
return a structured JSON classification.

{project_context}

Raw task text:
\"\"\"
{raw_text}
\"\"\"

Return ONLY valid JSON in this exact shape:
{{
  "kind": "task|waiting|commitment|idea|reference",
  "normalized_title": "Clear English title",
  "project_guess": "project name or null",
  "project_confidence": "low|medium|high",
  "next_action": "First concrete action or null",
  "due_hint": "ISO date or natural language date hint or null",
  "substeps": ["step 1", "step 2"],
  "confidence": "low|medium|high",
  "ambiguities": ["ambiguity 1"],
  "notes_for_user": "Optional note or null",
  "internal_rationale": "Brief internal reasoning"
}}
"""


def _fallback_classification(raw_text: str) -> TaskClassificationResult:
    text_lower = raw_text.lower()
    if text_lower.startswith("idea:"):
        kind = TaskKind.IDEA
        title = raw_text[5:].strip() or raw_text
    elif "жду" in text_lower or "waiting" in text_lower or "wait for" in text_lower:
        kind = TaskKind.WAITING
        title = raw_text
    elif "обещал" in text_lower or "promised" in text_lower:
        kind = TaskKind.COMMITMENT
        title = raw_text
    else:
        kind = TaskKind.TASK
        title = raw_text

    return TaskClassificationResult(
        kind=kind,
        normalized_title=title[:500],
        confidence=ConfidenceBand.LOW,
        project_confidence=ConfidenceBand.LOW,
    )


def _fallback_normalization(raw_text: str) -> NormalizationResult:
    return NormalizationResult(
        intent_summary=raw_text[:500].strip() or "unknown",
        is_multi_item=False,
        entities=[],
        language="en",
    )


def _fallback_pipeline(raw_text: str, project_fallback: str = "Personal") -> PipelineResult:
    legacy = _fallback_classification(raw_text)
    return PipelineResult(
        type=legacy.kind,
        project=project_fallback,
        title=legacy.normalized_title,
        next_action=legacy.next_action or "",
        confidence=ConfidenceBand.LOW,
        intent_summary=raw_text[:500],
    )


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])
    return text


class LLMService:
    def __init__(self, provider: str, model: str, api_key: str, base_url: str = "") -> None:
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self._base_url = base_url

    def _get_client(self):
        from openai import OpenAI

        if self._provider == "ollama":
            return OpenAI(
                base_url=self._base_url or "http://localhost:11434/v1",
                api_key="ollama",
            )
        return OpenAI(api_key=self._api_key)

    def _call_llm_sync(self, prompt: str, step_name: str = "") -> str:
        import re

        client = self._get_client()
        messages: list[dict] = []
        if self._provider == "ollama":
            messages.append({"role": "system", "content": "/no_think"})
        messages.append({"role": "user", "content": prompt})
        logger.info(
            "llm_request",
            step=step_name,
            model=self._model,
            provider=self._provider,
            prompt_chars=len(prompt),
            prompt=prompt,
        )
        response = client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.2,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        logger.info(
            "llm_response",
            step=step_name,
            model=self._model,
            response_chars=len(content),
            response=content,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
        )
        if "<think>" in content:
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        return content

    async def _call_and_parse(
        self,
        prompt: str,
        schema: type[T],
        step_name: str,
        retries: int = 2,
    ) -> T | None:
        for attempt in range(retries):
            try:
                raw_response = await asyncio.to_thread(self._call_llm_sync, prompt, step_name)
                raw_response = _strip_code_fences(raw_response)
                data = json.loads(raw_response)
                result = schema.model_validate(data)
                logger.info(
                    "llm_step_success",
                    step=step_name,
                    model=self._model,
                    attempt=attempt,
                )
                return result
            except Exception as e:
                logger.warning(
                    "llm_step_failed",
                    step=step_name,
                    attempt=attempt,
                    error=str(e),
                )
                if attempt == retries - 1:
                    break
        return None

    async def normalize(self, raw_title: str, raw_description: str = "") -> NormalizationResult:
        prompt = NORMALIZE.format(
            raw_title=raw_title,
            raw_description=raw_description or "(none)",
        )
        result = await self._call_and_parse(prompt, NormalizationResult, "normalize")
        if result is not None:
            return result
        logger.info("normalize_fallback", raw_title=raw_title[:100])
        return _fallback_normalization(raw_title)

    async def classify_route_title(
        self,
        raw_text: str,
        intent_summary: str,
        project_context: str,
        custom_instructions: str | None = None,
    ) -> ClassifyRouteResult | None:
        prompt = CLASSIFY_ROUTE_TITLE.format(
            raw_text=raw_text,
            intent_summary=intent_summary,
            project_context=project_context,
        )
        if custom_instructions:
            prompt += f"\n\nProject-specific instructions:\n{custom_instructions}"
        return await self._call_and_parse(prompt, ClassifyRouteResult, "classify_route_title")

    async def generate_description(self, raw_description: str, title: str) -> DescriptionResult | None:
        prompt = DESCRIPTION.format(raw_description=raw_description or "(none)", title=title)
        return await self._call_and_parse(prompt, DescriptionResult, "description")

    async def generate_steps(self, title: str, next_action: str) -> StepsResult | None:
        prompt = STEPS.format(title=title, next_action=next_action)
        return await self._call_and_parse(prompt, StepsResult, "steps")

    async def disambiguate(self, raw_text: str, intent_summary: str) -> DisambiguationResult | None:
        prompt = DISAMBIGUATE.format(raw_text=raw_text, intent_summary=intent_summary)
        return await self._call_and_parse(prompt, DisambiguationResult, "disambiguate")

    async def run_pipeline(
        self,
        raw_text: str,
        project_context: str,
        raw_description: str = "",
        custom_instructions: str | None = None,
        include_description: bool = False,
        include_steps: bool = False,
        project_fallback: str = "Personal",
    ) -> PipelineResult:
        norm = await self.normalize(raw_text, raw_description)

        # Use LLM-rewritten title for classify step if available
        classify_input = norm.rewritten_title if norm.rewritten_title else raw_text

        classify_result = await self.classify_route_title(
            raw_text=classify_input,
            intent_summary=norm.intent_summary,
            project_context=project_context,
            custom_instructions=custom_instructions,
        )

        if classify_result is None:
            logger.info("pipeline_fallback", raw_text=raw_text[:100])
            return _fallback_pipeline(raw_text, project_fallback)

        pipeline = PipelineResult(
            type=classify_result.type,
            project=classify_result.project,
            title=classify_result.title,
            next_action=classify_result.next_action,
            confidence=classify_result.confidence,
            due_hint=classify_result.due_hint,
            reasoning=classify_result.reasoning,
            intent_summary=norm.intent_summary,
            language=norm.language,
            is_multi_item=norm.is_multi_item,
            entities=norm.entities,
        )

        if classify_result.confidence == ConfidenceBand.LOW:
            disambig = await self.disambiguate(raw_text, norm.intent_summary)
            if disambig is not None:
                pipeline = pipeline.model_copy(update={"disambiguation_options": disambig.options})

        # Always run description step — restructures + translates notes to English
        desc = await self.generate_description(raw_description, classify_result.title)
        if desc is not None and desc.description:
            pipeline = pipeline.model_copy(update={"description": desc.description})

        if include_steps:
            steps = await self.generate_steps(classify_result.title, classify_result.next_action)
            if steps is not None:
                pipeline = pipeline.model_copy(update={"steps": steps.steps})

        logger.info(
            "pipeline_complete",
            type=pipeline.type,
            project=pipeline.project,
            confidence=pipeline.confidence,
            model=self._model,
        )
        return pipeline

    async def classify_task(
        self,
        raw_text: str,
        project_context: str,
        custom_instructions: str | None = None,
    ) -> TaskClassificationResult:
        prompt = _CLASSIFY_PROMPT_TEMPLATE.format(
            raw_text=raw_text,
            project_context=project_context,
        )
        if custom_instructions:
            prompt += f"\n\nProject-specific instructions:\n{custom_instructions}"

        for attempt in range(2):
            try:
                raw_response = await asyncio.to_thread(self._call_llm_sync, prompt)
                raw_response = _strip_code_fences(raw_response)
                data = json.loads(raw_response)
                result = TaskClassificationResult.model_validate(data)
                logger.info(
                    "llm_classification_success",
                    kind=result.kind,
                    confidence=result.confidence,
                    model=self._model,
                    attempt=attempt,
                )
                return result
            except Exception as e:
                logger.warning(
                    "llm_classification_failed",
                    attempt=attempt,
                    error=str(e),
                )
                if attempt == 1:
                    break

        logger.info("llm_classification_fallback", raw_text=raw_text[:100])
        return _fallback_classification(raw_text)

    async def generate_project_description(
        self,
        project_name: str,
        sample_tasks: list[str],
    ) -> dict[str, str | list[str]]:
        tasks_block = "\n".join(f"- {t}" for t in sample_tasks[:20])
        prompt = f"""Analyze these tasks from the project \"{project_name}\" and generate metadata.

Tasks:
{tasks_block}

Return ONLY valid JSON:
{{
  "description": "2-3 sentence description of what this project is about",
  "aliases": ["alias1", "alias2"],
  "keywords": ["keyword1", "keyword2"],
  "example_patterns": ["pattern that indicates this project"]
}}"""

        for attempt in range(2):
            try:
                raw_response = await asyncio.to_thread(self._call_llm_sync, prompt)
                raw_response = _strip_code_fences(raw_response)
                data = json.loads(raw_response)
                description = data.get("description") if isinstance(data, dict) else None
                aliases = data.get("aliases") if isinstance(data, dict) else None
                keywords = data.get("keywords") if isinstance(data, dict) else None
                example_patterns = data.get("example_patterns") if isinstance(data, dict) else None
                logger.info("project_description_generated", project=project_name)
                return {
                    "description": description if isinstance(description, str) else "",
                    "aliases": aliases if isinstance(aliases, list) else [],
                    "keywords": keywords if isinstance(keywords, list) else [],
                    "example_patterns": (
                        example_patterns if isinstance(example_patterns, list) else []
                    ),
                }
            except Exception as e:
                logger.warning(
                    "project_description_generation_failed", attempt=attempt, error=str(e)
                )
                if attempt == 1:
                    break

        return {
            "description": f"Tasks related to {project_name}",
            "aliases": [],
            "keywords": [],
            "example_patterns": [],
        }

    async def rewrite_title(self, raw_text: str) -> str:
        prompt = (
            "You are a productivity assistant. Rewrite the following raw task note into a "
            "concise, action-oriented title in clear English. "
            "Start with a verb. Return ONLY the title — no JSON, no explanation, no quotes.\n\n"
            f"Raw text: {raw_text}"
        )
        for attempt in range(2):
            try:
                result = await asyncio.to_thread(self._call_llm_sync, prompt)
                title = result.strip().strip('"').strip("'")[:500]
                if title:
                    logger.info("llm_rewrite_success", model=self._model)
                    return title
            except Exception as exc:
                logger.warning("llm_rewrite_failed", attempt=attempt, error=str(exc))
        return raw_text

    def generate_daily_review(self, context_payload: dict[str, list[dict[str, str]]]) -> str:
        lines = ["Here is the daily task summary:"]
        if context_payload.get("active_tasks"):
            lines.append(f"\nActive tasks ({len(context_payload['active_tasks'])}):")
            for t in context_payload["active_tasks"]:
                lines.append(f"  • {t['title']}")
        if context_payload.get("waiting_items"):
            lines.append(f"\nWaiting items ({len(context_payload['waiting_items'])}):")
            for t in context_payload["waiting_items"]:
                lines.append(f"  • {t['title']}")
        if context_payload.get("stale_tasks"):
            lines.append(f"\nStale tasks ({len(context_payload['stale_tasks'])}):")
            for t in context_payload["stale_tasks"]:
                lines.append(f"  • {t['title']}")
        return "\n".join(lines)
