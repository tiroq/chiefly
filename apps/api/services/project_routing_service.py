"""
Project routing service - determines which project a task belongs to.
"""

from __future__ import annotations

import uuid
import re

from apps.api.logging import get_logger
from core.domain.enums import ConfidenceBand
from db.models.project import Project

logger = get_logger(__name__)

DEFAULT_PROJECT_SLUG = "personal"
NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")


def _keyword_matches(keyword: str, text: str) -> bool:
    """Match keyword as a whole word (case-insensitive)."""
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _tokenize(text: str) -> list[str]:
    return NON_ALNUM_PATTERN.sub(" ", text).split()


def _build_implicit_aliases(available_projects: list[Project]) -> dict[str, uuid.UUID]:
    aliases: dict[str, uuid.UUID] = {}

    for project in available_projects:
        name = project.name.lower().strip()
        if name:
            if name not in aliases:
                aliases[name] = project.id

        for token in _tokenize(name):
            if len(token) >= 3:
                if token not in aliases:
                    aliases[token] = project.id

        for token in _tokenize(project.slug.lower()):
            if len(token) >= 3:
                if token not in aliases:
                    aliases[token] = project.id

    for project in available_projects:
        if project.slug == "family":
            if "kids" not in aliases:
                aliases["kids"] = project.id
            if "wife" not in aliases:
                aliases["wife"] = project.id
            break

    return aliases


class ProjectRoutingService:
    def route(
        self,
        raw_text: str,
        llm_project_guess: str | None,
        llm_project_confidence: ConfidenceBand,
        available_projects: list[Project],
        aliases: dict[str, uuid.UUID] | None = None,
    ) -> tuple[Project | None, ConfidenceBand]:
        """
        Returns (project, confidence_band) for the best matching project.

        Layered logic:
        1. Alias keyword matching in raw_text (when aliases provided)
        2. Exact project name match with LLM guess
        3. Fuzzy LLM project_guess match against project names
        4. Fallback to default project
        """
        slug_map = {p.slug: p for p in available_projects}
        id_map = {p.id: p for p in available_projects}
        name_map = {p.name.lower(): p for p in available_projects}

        effective_aliases = (
            aliases if aliases is not None else _build_implicit_aliases(available_projects)
        )

        if effective_aliases:
            for keyword, target_project_id in effective_aliases.items():
                if _keyword_matches(keyword, raw_text):
                    project = id_map.get(target_project_id)
                    if project is None:
                        continue
                    logger.info(
                        "project_routed_by_alias_keyword",
                        keyword=keyword,
                        project_id=target_project_id,
                    )
                    return project, ConfidenceBand.HIGH

        # 2. Exact project name match with LLM guess
        if llm_project_guess:
            guess_lower = llm_project_guess.lower().strip()
            if guess_lower in name_map:
                project = name_map[guess_lower]
                logger.info("project_routed_by_exact_llm_name", guess=llm_project_guess)
                return project, llm_project_confidence

            # 3. Partial match - llm guess contained in project name or vice versa
            for name_lower, project in name_map.items():
                if guess_lower in name_lower or name_lower in guess_lower:
                    logger.info("project_routed_by_partial_llm_name", guess=llm_project_guess)
                    return project, ConfidenceBand.MEDIUM

        # 4. Fallback to default
        if DEFAULT_PROJECT_SLUG in slug_map:
            logger.info("project_routed_by_default", slug=DEFAULT_PROJECT_SLUG)
            return slug_map[DEFAULT_PROJECT_SLUG], ConfidenceBand.LOW

        # No project available at all
        if available_projects:
            return available_projects[0], ConfidenceBand.LOW

        return None, ConfidenceBand.LOW

    def derive_confidence_band(self, score: float) -> ConfidenceBand:
        if score >= 0.75:
            return ConfidenceBand.HIGH
        if score >= 0.45:
            return ConfidenceBand.MEDIUM
        return ConfidenceBand.LOW
