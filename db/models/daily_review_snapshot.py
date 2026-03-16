import uuid
from datetime import datetime

from sqlalchemy import DateTime, JSON, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class DailyReviewSnapshot(Base):
    __tablename__ = "daily_review_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
