from sqlalchemy import BigInteger, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DeliveryStatus, MessageChannel, MessageSource
from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "messages"

    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)

    source: Mapped[MessageSource] = mapped_column(Enum(MessageSource, native_enum=False), nullable=False)
    channel: Mapped[MessageChannel] = mapped_column(Enum(MessageChannel, native_enum=False), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_update_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, native_enum=False), default=DeliveryStatus.PENDING, nullable=False
    )
    delivery_error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    lead: Mapped["Lead"] = relationship("Lead", back_populates="messages")
    input_ai_runs: Mapped[list["AIRun"]] = relationship("AIRun", back_populates="input_message")

    __table_args__ = (
        Index("ix_messages_lead_created", "lead_id", "created_at"),
        Index("ix_messages_telegram_update_unique", "telegram_update_id", unique=True),
    )
