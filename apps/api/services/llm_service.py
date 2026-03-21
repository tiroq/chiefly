"""
LLM classification service with provider abstraction.
"""

from __future__ import annotations

import json
import asyncio

from apps.api.logging import get_logger
from core.domain.enums import ConfidenceBand, TaskKind
from core.schemas.llm import TaskClassificationResult

logger = get_logger(__name__)

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
    """Simple heuristic fallback when LLM fails."""
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

    def _call_llm_sync(self, prompt: str) -> str:
        """Synchronous LLM call — always run via asyncio.to_thread."""
        client = self._get_client()
        response = client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1024,
        )
        return response.choices[0].message.content or ""

    async def classify_task(
        self,
        raw_text: str,
        project_context: str,
        custom_instructions: str | None = None,
    ) -> TaskClassificationResult:
        """Classify raw task text using LLM.  Non-blocking — runs the sync
        OpenAI call in a thread pool via asyncio.to_thread."""
        prompt = _CLASSIFY_PROMPT_TEMPLATE.format(
            raw_text=raw_text,
            project_context=project_context,
        )
        if custom_instructions:
            prompt += f"\n\nProject-specific instructions:\n{custom_instructions}"

        for attempt in range(2):
            try:
                raw_response = await asyncio.to_thread(self._call_llm_sync, prompt)
                # Strip markdown code fences if present
                raw_response = raw_response.strip()
                if raw_response.startswith("```"):
                    lines = raw_response.split("\n")
                    raw_response = "\n".join(lines[1:-1])

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
        """Generate a project description, aliases, and keywords from sample tasks.

        Returns dict with description, aliases, keywords, and example_patterns.
        """
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
                raw_response = raw_response.strip()
                if raw_response.startswith("```"):
                    lines = raw_response.split("\n")
                    raw_response = "\n".join(lines[1:-1])
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
        """Ask the LLM to rewrite raw task text into a clean, actionable title.

        Returns the rewritten title, or the original text if the LLM fails.
        """
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
