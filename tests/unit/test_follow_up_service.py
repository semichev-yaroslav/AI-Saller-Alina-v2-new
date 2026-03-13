from datetime import UTC, datetime, timedelta

from app.core.enums import DeliveryStatus, LeadStage, MessageChannel, MessageSource
from app.db.models.lead import Lead
from app.db.models.message import Message
from app.services.follow_up_service import FollowUpService


class CaptureSender:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def send_message(self, chat_id: int, text: str) -> int:
        self.calls.append((chat_id, text))
        return len(self.calls)


def test_follow_up_service_sends_due_message_and_increments_step(db_session) -> None:
    lead = Lead(
        telegram_user_id=9991,
        telegram_chat_id=9991,
        username="fup_user",
        full_name="Follow Up User",
        stage=LeadStage.ENGAGED,
        follow_up_step=0,
        next_follow_up_at=datetime.now(UTC) - timedelta(minutes=1),
        do_not_contact=False,
    )
    db_session.add(lead)
    db_session.commit()
    db_session.add(
        Message(
            lead_id=lead.id,
            source=MessageSource.USER,
            channel=MessageChannel.TELEGRAM,
            text="Привет",
            delivery_status=DeliveryStatus.SENT,
        )
    )
    db_session.commit()

    sender = CaptureSender()
    sent = FollowUpService(db_session, sender).process_due(limit=10)
    db_session.refresh(lead)

    assert sent == 1
    assert lead.follow_up_step == 1
    assert lead.next_follow_up_at is not None
    assert len(sender.calls) == 1


def test_follow_up_service_skips_non_telegram_dialogs(db_session) -> None:
    lead = Lead(
        telegram_user_id=9992,
        telegram_chat_id=9992,
        username="sim_user",
        full_name="Simulation User",
        stage=LeadStage.ENGAGED,
        follow_up_step=0,
        next_follow_up_at=datetime.now(UTC) - timedelta(minutes=1),
        do_not_contact=False,
    )
    db_session.add(lead)
    db_session.commit()
    db_session.add(
        Message(
            lead_id=lead.id,
            source=MessageSource.USER,
            channel=MessageChannel.API_SIMULATION,
            text="Привет",
            delivery_status=DeliveryStatus.SENT,
        )
    )
    db_session.commit()

    sender = CaptureSender()
    sent = FollowUpService(db_session, sender).process_due(limit=10)
    db_session.refresh(lead)

    assert sent == 0
    assert lead.follow_up_step == 0
    assert lead.next_follow_up_at is not None
    assert len(sender.calls) == 0
