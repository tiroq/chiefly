"""
Unit tests for project routing service.
"""

import uuid
from datetime import datetime, timezone

import pytest

from apps.api.services.project_routing_service import ProjectRoutingService
from core.domain.enums import ConfidenceBand, ProjectType
from db.models.project import Project


def make_project(name: str, slug: str, project_type: ProjectType = ProjectType.PERSONAL) -> Project:
    return Project(
        id=uuid.uuid4(),
        name=name,
        slug=slug,
        google_tasklist_id=f"{slug}-list",
        project_type=project_type,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def projects():
    return [
        make_project("NFT Gateway", "nft-gateway", ProjectType.CLIENT),
        make_project("Personal", "personal", ProjectType.PERSONAL),
        make_project("Family", "family", ProjectType.FAMILY),
        make_project("Writing", "writing", ProjectType.WRITING),
        make_project("Infra", "infra", ProjectType.OPS),
    ]


@pytest.fixture
def routing():
    return ProjectRoutingService()


class TestProjectRouting:
    def test_keyword_alias_nft(self, routing, projects):
        project, confidence = routing.route(
            raw_text="Deploy nft contract",
            llm_project_guess=None,
            llm_project_confidence=ConfidenceBand.LOW,
            available_projects=projects,
        )
        assert project is not None
        assert project.slug == "nft-gateway"
        assert confidence == ConfidenceBand.HIGH

    def test_keyword_alias_family(self, routing, projects):
        project, confidence = routing.route(
            raw_text="Call kids school",
            llm_project_guess=None,
            llm_project_confidence=ConfidenceBand.LOW,
            available_projects=projects,
        )
        assert project is not None
        assert project.slug == "family"

    def test_exact_llm_name_match(self, routing, projects):
        project, confidence = routing.route(
            raw_text="Some task text",
            llm_project_guess="Writing",
            llm_project_confidence=ConfidenceBand.HIGH,
            available_projects=projects,
        )
        assert project is not None
        assert project.slug == "writing"

    def test_partial_llm_name_match(self, routing, projects):
        project, confidence = routing.route(
            raw_text="Some task text",
            llm_project_guess="NFT",
            llm_project_confidence=ConfidenceBand.MEDIUM,
            available_projects=projects,
        )
        assert project is not None
        assert project.slug == "nft-gateway"
        assert confidence == ConfidenceBand.MEDIUM

    def test_fallback_to_personal(self, routing, projects):
        project, confidence = routing.route(
            raw_text="Buy milk",
            llm_project_guess=None,
            llm_project_confidence=ConfidenceBand.LOW,
            available_projects=projects,
        )
        assert project is not None
        assert project.slug == "personal"
        assert confidence == ConfidenceBand.LOW

    def test_no_projects_returns_none(self, routing):
        project, confidence = routing.route(
            raw_text="Buy milk",
            llm_project_guess=None,
            llm_project_confidence=ConfidenceBand.LOW,
            available_projects=[],
        )
        assert project is None

    def test_derive_confidence_band_high(self, routing):
        assert routing.derive_confidence_band(0.9) == ConfidenceBand.HIGH

    def test_derive_confidence_band_medium(self, routing):
        assert routing.derive_confidence_band(0.6) == ConfidenceBand.MEDIUM

    def test_derive_confidence_band_low(self, routing):
        assert routing.derive_confidence_band(0.2) == ConfidenceBand.LOW
