import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class TelegramReviewSession(Base):
    __tablename__ = "telegram_review_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    stable_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_records.stable_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    telegram_chat_id: Mapped[str] = mapped_column(String(100), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    base_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("task_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    base_google_updated: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proposed_changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = ()
