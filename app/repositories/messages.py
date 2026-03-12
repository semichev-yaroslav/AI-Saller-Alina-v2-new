from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import DeliveryStatus, MessageChannel, MessageSource
from app.db.models.message import Message


class MessageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        lead_id: str,
        source: MessageSource,
        channel: MessageChannel,
        text: str,
        telegram_message_id: int | None = None,
        telegram_update_id: int | None = None,
        delivery_status: DeliveryStatus = DeliveryStatus.PENDING,
        delivery_error: str | None = None,
    ) -> Message:
        message = Message(
            lead_id=lead_id,
            source=source,
            channel=channel,
            text=text,
            telegram_message_id=telegram_message_id,
            telegram_update_id=telegram_update_id,
            delivery_status=delivery_status,
            delivery_error=delivery_error,
        )
        self.db.add(message)
        self.db.flush()
        return message

    def create_incoming_if_new(
        self,
        *,
        lead_id: str,
        channel: MessageChannel,
        text: str,
        telegram_message_id: int | None = None,
        telegram_update_id: int | None = None,
    ) -> tuple[Message | None, bool]:
        try:
            message = self.create(
                lead_id=lead_id,
                source=MessageSource.USER,
                channel=channel,
                text=text,
                telegram_message_id=telegram_message_id,
                telegram_update_id=telegram_update_id,
                delivery_status=DeliveryStatus.SENT,
            )
            return message, True
        except IntegrityError:
            self.db.rollback()
            return None, False

    def list_by_lead(self, lead_id: str, *, limit: int = 100, offset: int = 0) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.lead_id == lead_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt))

    def get_recent_for_context(self, lead_id: str, *, limit: int) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.lead_id == lead_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        rows = list(self.db.scalars(stmt))
        rows.reverse()
        return rows
