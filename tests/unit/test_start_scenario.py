from decimal import Decimal
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models.ai_run import AIRun
from app.db.models.lead import Lead
from app.db.models.service import Service
from app.core.enums import IntentType, LeadStage, MessageChannel
from app.services.message_processor import IncomingMessageDTO, MessageProcessor


class FailingAnalyzer:
    model_name = "failing"

    def analyze(self, message_text, context):
        raise AssertionError("Analyzer should not be called for /start scenario")


def test_start_command_uses_separate_funnel_scenario(db_session) -> None:
    db_session.add(
        Service(
            name="AI Saller Alina — AI-менеджер по продажам",
            description="Описание",
            price_from=Decimal("120000.00"),
            currency="RUB",
            is_active=True,
        )
    )
    db_session.commit()

    processor = MessageProcessor(db_session, analyzer=FailingAnalyzer())
    result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=9001,
            telegram_chat_id=9001,
            username="start_user",
            full_name="Start User",
            text="/start",
            channel=MessageChannel.API_SIMULATION,
        )
    )

    ai_run = db_session.scalar(select(AIRun).where(AIRun.input_message_id == result.incoming_message_id))

    assert result.intent == IntentType.GREETING
    assert result.stage == LeadStage.ENGAGED
    assert "Покажу, как AI-менеджер" in result.reply_text
    assert "чем занимается ваш бизнес" in result.reply_text

    assert ai_run is not None
    assert ai_run.model == "rule-start-v1"
    assert ai_run.prompt_version.endswith("-start")


def test_start_resets_previous_booked_state(db_session) -> None:
    db_session.add(
        Service(
            name="AI Saller Alina — AI-менеджер по продажам",
            description="Описание",
            price_from=Decimal("120000.00"),
            currency="RUB",
            is_active=True,
        )
    )
    db_session.commit()

    lead = Lead(
        telegram_user_id=9010,
        telegram_chat_id=9010,
        username="booked_user",
        full_name="Booked User",
        stage=LeadStage.BOOKED,
        booking_slot_at=datetime(2026, 3, 20, 12, 0, tzinfo=UTC),
        do_not_contact=True,
        handoff_requested=True,
        qualification_data={"priority": "not_lose_leads"},
    )
    db_session.add(lead)
    db_session.commit()

    processor = MessageProcessor(db_session, analyzer=FailingAnalyzer())
    result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=9010,
            telegram_chat_id=9010,
            username="booked_user",
            full_name="Booked User",
            text="/start",
            channel=MessageChannel.API_SIMULATION,
        )
    )

    refreshed = db_session.get(Lead, result.lead_id)

    assert refreshed is not None
    assert result.stage == LeadStage.ENGAGED
    assert refreshed.stage == LeadStage.ENGAGED
    assert refreshed.booking_slot_at is None
    assert refreshed.do_not_contact is False
    assert refreshed.handoff_requested is False
    assert refreshed.qualification_data == {}
