from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import DeliveryStatus, LeadStage, MessageChannel, MessageSource
from app.db.models.lead import Lead
from app.repositories.messages import MessageRepository
from app.services.schedule import follow_up_message, schedule_follow_up_at

logger = logging.getLogger(__name__)


class TelegramSenderProtocol(Protocol):
    def send_message(self, chat_id: int, text: str) -> int | None:
        ...


class FollowUpService:
    def __init__(self, db: Session, telegram_sender: TelegramSenderProtocol | None) -> None:
        self.db = db
        self.telegram_sender = telegram_sender
        self.messages_repo = MessageRepository(db)

    def process_due(self, *, limit: int = 20) -> int:
        if self.telegram_sender is None:
            return 0

        now_utc = datetime.now(UTC)
        leads = self._get_due_leads(now_utc=now_utc, limit=limit)
        sent_count = 0

        for lead in leads:
            next_step = lead.follow_up_step + 1
            if next_step > 3:
                lead.next_follow_up_at = None
                self.db.commit()
                continue

            outgoing = self.messages_repo.create(
                lead_id=lead.id,
                source=MessageSource.ASSISTANT,
                channel=MessageChannel.TELEGRAM,
                text=follow_up_message(next_step),
                delivery_status=DeliveryStatus.PENDING,
            )
            self.db.commit()

            try:
                telegram_message_id = self.telegram_sender.send_message(
                    chat_id=lead.telegram_chat_id,
                    text=outgoing.text,
                )
                outgoing.telegram_message_id = telegram_message_id
                outgoing.delivery_status = DeliveryStatus.SENT
                outgoing.delivery_error = None
                lead.follow_up_step = next_step
                lead.last_bot_message_at = now_utc
                if next_step >= 3:
                    lead.next_follow_up_at = None
                else:
                    lead.next_follow_up_at = schedule_follow_up_at(now_utc, next_step + 1)
                self.db.commit()
                sent_count += 1
            except Exception as exc:  # noqa: BLE001
                outgoing.delivery_status = DeliveryStatus.FAILED
                outgoing.delivery_error = str(exc)
                lead.next_follow_up_at = now_utc + timedelta(minutes=15)
                self.db.commit()
                logger.warning("Follow-up delivery failed", extra={"lead_id": lead.id, "error": str(exc)})

        return sent_count

    def _get_due_leads(self, *, now_utc: datetime, limit: int) -> list[Lead]:
        stmt = (
            select(Lead)
            .where(Lead.next_follow_up_at.is_not(None))
            .where(Lead.next_follow_up_at <= now_utc)
            .where(Lead.do_not_contact.is_(False))
            .where(Lead.stage.notin_([LeadStage.BOOKED, LeadStage.LOST]))
            .order_by(Lead.next_follow_up_at.asc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))
