"""
Seed script to create example projects in the database.
Run: python scripts/seed_projects.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.config import get_settings
from core.domain.enums import ProjectType
from core.utils.text import slugify
from db.base import Base
from db.models.project import Project

PROJECTS = [
    {"name": "NFT Gateway", "google_tasklist_id": "REPLACE_WITH_TASKLIST_ID", "project_type": ProjectType.CLIENT},
    {"name": "Client A", "google_tasklist_id": "REPLACE_WITH_TASKLIST_ID", "project_type": ProjectType.CLIENT},
    {"name": "Client B", "google_tasklist_id": "REPLACE_WITH_TASKLIST_ID", "project_type": ProjectType.CLIENT},
    {"name": "Personal", "google_tasklist_id": "REPLACE_WITH_TASKLIST_ID", "project_type": ProjectType.PERSONAL},
    {"name": "Family", "google_tasklist_id": "REPLACE_WITH_TASKLIST_ID", "project_type": ProjectType.FAMILY},
    {"name": "Writing", "google_tasklist_id": "REPLACE_WITH_TASKLIST_ID", "project_type": ProjectType.WRITING},
    {"name": "Infra", "google_tasklist_id": "REPLACE_WITH_TASKLIST_ID", "project_type": ProjectType.OPS},
    {"name": "Internal", "google_tasklist_id": "REPLACE_WITH_TASKLIST_ID", "project_type": ProjectType.INTERNAL},
]


async def seed() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as session:
        now = datetime.now(tz=timezone.utc)
        for proj_data in PROJECTS:
            slug = slugify(proj_data["name"])
            existing = await session.execute(
                __import__("sqlalchemy").select(Project).where(Project.slug == slug)
            )
            if existing.scalar_one_or_none() is not None:
                print(f"  Project already exists: {proj_data['name']} (skipping)")
                continue

            project = Project(
                id=uuid.uuid4(),
                name=proj_data["name"],
                slug=slug,
                google_tasklist_id=proj_data["google_tasklist_id"],
                project_type=proj_data["project_type"],
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(project)
            print(f"  Created project: {proj_data['name']} (slug={slug})")

        await session.commit()
        print("Seeding complete.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
