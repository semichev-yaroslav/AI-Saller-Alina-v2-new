from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import IntentType, LeadStage
from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class Lead(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "leads"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    stage: Mapped[LeadStage] = mapped_column(
        Enum(LeadStage, native_enum=False), default=LeadStage.NEW, nullable=False, index=True
    )
    last_intent: Mapped[IntentType | None] = mapped_column(Enum(IntentType, native_enum=False), nullable=True)
    qualification_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    follow_up_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    do_not_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_user_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_bot_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    booking_slot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handoff_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    messages: Mapped[list["Message"]] = relationship("Message", back_populates="lead", cascade="all,delete-orphan")
    ai_runs: Mapped[list["AIRun"]] = relationship("AIRun", back_populates="lead", cascade="all,delete-orphan")
