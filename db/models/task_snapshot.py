from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

import uuid

from db.base import Base


class TaskSnapshot(Base):
    __tablename__ = "task_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stable_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_records.stable_id", ondelete="SET NULL"),
        nullable=True,
    )
    tasklist_id: Mapped[str] = mapped_column(String(255), nullable=False)
    task_id: Mapped[str] = mapped_column(String(255), nullable=False)
    google_updated: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        Index("ix_task_snapshots_tasklist_task", "tasklist_id", "task_id", "fetched_at"),
        Index("ix_task_snapshots_stable_id_fetched", "stable_id", "fetched_at"),
        Index(
            "uq_task_snapshots_latest",
            "stable_id",
            unique=True,
            postgresql_where="is_latest = true",
        ),
        Index("ix_task_snapshots_content_hash", "content_hash"),
    )
