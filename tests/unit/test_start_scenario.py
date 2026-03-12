from decimal import Decimal

from sqlalchemy import select

from app.db.models.ai_run import AIRun
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
    assert "Вы перешли по рекламе" in result.reply_text
    assert "сколько заявок в месяц" in result.reply_text

    assert ai_run is not None
    assert ai_run.model == "rule-start-v1"
    assert ai_run.prompt_version.endswith("-start")
