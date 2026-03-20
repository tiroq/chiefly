import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ProjectPromptVersion(Base):
    __tablename__ = "project_prompt_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification_prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    routing_prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    examples_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_project_prompt_versions_project_id_version_no",
            "project_id",
            "version_no",
            unique=True,
        ),
        Index("ix_project_prompt_versions_project_id_is_active", "project_id", "is_active"),
    )
