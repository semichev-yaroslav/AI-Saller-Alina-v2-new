from sqlalchemy import Enum, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AIRunStatus, IntentType, LeadStage
from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class AIRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_runs"

    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    input_message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)

    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")

    intent: Mapped[IntentType | None] = mapped_column(Enum(IntentType, native_enum=False), nullable=True)
    predicted_stage: Mapped[LeadStage | None] = mapped_column(Enum(LeadStage, native_enum=False), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[AIRunStatus] = mapped_column(
        Enum(AIRunStatus, native_enum=False), default=AIRunStatus.SUCCESS, nullable=False
    )
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    lead: Mapped["Lead"] = relationship("Lead", back_populates="ai_runs")
    input_message: Mapped["Message"] = relationship("Message", back_populates="input_ai_runs")
