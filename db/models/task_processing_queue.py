import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.enums import ProcessingReason, ProcessingStatus
from db.base import Base


class TaskProcessingQueue(Base):
    __tablename__ = "task_processing_queue"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("source_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    stable_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_records.stable_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    processing_status: Mapped[str] = mapped_column(
        Enum(
            ProcessingStatus,
            name="processing_status_enum",
            create_constraint=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ProcessingStatus.PENDING,
    )
    processing_reason: Mapped[str] = mapped_column(
        Enum(
            ProcessingReason,
            name="processing_reason_enum",
            create_constraint=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    content_hash_at_processing: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_tpq_processing_status", "processing_status"),
        Index("ix_tpq_source_task_id", "source_task_id"),
        Index("ix_tpq_created_at", "created_at"),
        Index("ix_tpq_status_created", "processing_status", "created_at"),
    )
