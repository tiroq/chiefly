"""
Project routing service - determines which project a task belongs to.
"""

from __future__ import annotations

import re

from apps.api.logging import get_logger
from core.domain.enums import ConfidenceBand
from db.models.project import Project

logger = get_logger(__name__)

# Keyword aliases: keyword -> project slug
# Keywords are matched as whole words (word boundary aware)
PROJECT_KEYWORD_ALIASES: dict[str, str] = {
    "nft gateway": "nft-gateway",
    "nft": "nft-gateway",
    "client a": "client-a",
    "client b": "client-b",
    "family": "family",
    "kids": "family",
    "wife": "family",
    "blog": "writing",
    "article": "writing",
    "writing": "writing",
    "infra": "infra",
    "devops": "infra",
    "deploy": "infra",
}

DEFAULT_PROJECT_SLUG = "personal"


def _keyword_matches(keyword: str, text: str) -> bool:
    """Match keyword as a whole word (case-insensitive)."""
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


class ProjectRoutingService:
    def route(
        self,
        raw_text: str,
        llm_project_guess: str | None,
        llm_project_confidence: ConfidenceBand,
        available_projects: list[Project],
    ) -> tuple[Project | None, ConfidenceBand]:
        """
        Returns (project, confidence_band) for the best matching project.

        Layered logic:
        1. Keyword alias matching in raw_text
        2. Exact project name match with LLM guess
        3. Fuzzy LLM project_guess match against project names
        4. Fallback to default project
        """
        slug_map = {p.slug: p for p in available_projects}
        name_map = {p.name.lower(): p for p in available_projects}

        # 1. Keyword alias match
        for keyword, target_slug in PROJECT_KEYWORD_ALIASES.items():
            if _keyword_matches(keyword, raw_text):
                if target_slug in slug_map:
                    logger.info(
                        "project_routed_by_keyword",
                        keyword=keyword,
                        slug=target_slug,
                    )
                    return slug_map[target_slug], ConfidenceBand.HIGH

        # 2. Exact project name match with LLM guess
        if llm_project_guess:
            guess_lower = llm_project_guess.lower().strip()
            if guess_lower in name_map:
                project = name_map[guess_lower]
                logger.info(
                    "project_routed_by_exact_llm_name", guess=llm_project_guess
                )
                return project, llm_project_confidence

            # 3. Partial match - llm guess contained in project name or vice versa
            for name_lower, project in name_map.items():
                if guess_lower in name_lower or name_lower in guess_lower:
                    logger.info(
                        "project_routed_by_partial_llm_name", guess=llm_project_guess
                    )
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
