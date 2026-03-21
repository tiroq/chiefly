import uuid
from datetime import datetime, timezone

from apps.api.services.project_routing_service import ProjectRoutingService
from core.domain.enums import ConfidenceBand, ProjectType
from db.models.project import Project


def make_project(project_id: uuid.UUID, name: str, slug: str) -> Project:
    return Project(
        id=project_id,
        name=name,
        slug=slug,
        google_tasklist_id=f"{slug}-list",
        project_type=ProjectType.PERSONAL,
        is_active=True,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def test_route_without_aliases_uses_llm_guess() -> None:
    routing = ProjectRoutingService()
    writing_id = uuid.uuid4()

    projects = [
        make_project(uuid.uuid4(), "NFT Gateway", "nft-gateway"),
        make_project(writing_id, "Writing", "writing"),
        make_project(uuid.uuid4(), "Personal", "personal"),
    ]

    project, confidence = routing.route(
        raw_text="Ship roadmap next week",
        llm_project_guess="Writing",
        llm_project_confidence=ConfidenceBand.MEDIUM,
        available_projects=projects,
        aliases=None,
    )

    assert project is not None
    assert project.id == writing_id
    assert confidence == ConfidenceBand.MEDIUM


def test_route_with_alias_match_returns_high_confidence() -> None:
    routing = ProjectRoutingService()
    nft_id = uuid.uuid4()

    projects = [
        make_project(nft_id, "NFT Gateway", "nft-gateway"),
        make_project(uuid.uuid4(), "Personal", "personal"),
    ]

    project, confidence = routing.route(
        raw_text="Deploy nft contract",
        llm_project_guess=None,
        llm_project_confidence=ConfidenceBand.LOW,
        available_projects=projects,
        aliases={"nft": nft_id},
    )

    assert project is not None
    assert project.id == nft_id
    assert confidence == ConfidenceBand.HIGH


def test_alias_match_takes_priority_over_llm_guess() -> None:
    routing = ProjectRoutingService()
    nft_id = uuid.uuid4()
    writing_id = uuid.uuid4()

    projects = [
        make_project(nft_id, "NFT Gateway", "nft-gateway"),
        make_project(writing_id, "Writing", "writing"),
        make_project(uuid.uuid4(), "Personal", "personal"),
    ]

    project, confidence = routing.route(
        raw_text="Prepare nft migration checklist",
        llm_project_guess="Writing",
        llm_project_confidence=ConfidenceBand.HIGH,
        available_projects=projects,
        aliases={"nft": nft_id},
    )

    assert project is not None
    assert project.id == nft_id
    assert confidence == ConfidenceBand.HIGH
