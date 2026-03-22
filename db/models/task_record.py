import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class TaskRecord(Base):
    __tablename__ = "task_records"

    stable_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    current_tasklist_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pointer_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_google_updated: Mapped[str | None] = mapped_column(String(255), nullable=True)
    consecutive_misses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="unadopted")
    processing_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    processing_status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "uq_task_records_pointer",
            "current_tasklist_id",
            "current_task_id",
            unique=True,
            postgresql_where="current_tasklist_id IS NOT NULL AND current_task_id IS NOT NULL",
        ),
        Index("ix_task_records_processing", "processing_status", "processing_status_updated_at"),
        Index("ix_task_records_state", "state", "last_seen_at"),
    )
