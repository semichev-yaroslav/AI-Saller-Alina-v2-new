from app.ai.contracts import AnalyzerContext, AnalyzerResult
from app.core.enums import IntentType, LeadStage, MessageChannel
from app.repositories.leads import LeadRepository
from app.services.message_processor import IncomingMessageDTO, MessageProcessor


class DummyAnalyzer:
    model_name = "dummy"

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        return AnalyzerResult(
            intent=IntentType.SERVICE_QUESTION,
            stage=LeadStage.QUALIFIED,
            reply_text="Скажите, откуда к вам обычно приходят заявки?",
            confidence=0.9,
            raw={"provider": "dummy"},
        )


def test_stop_phrase_blocks_dialog_until_new_user_message(db_session) -> None:
    processor = MessageProcessor(db_session, analyzer=DummyAnalyzer())

    stop_result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=3001,
            telegram_chat_id=3001,
            username="stop_user",
            full_name="Stop User",
            text="Стоп, не пишите",
            channel=MessageChannel.API_SIMULATION,
        )
    )
    lead = LeadRepository(db_session).get(stop_result.lead_id)

    assert stop_result.stage == LeadStage.LOST
    assert stop_result.reply_text.startswith("Понял, больше не буду писать.")
    assert lead is not None
    assert lead.do_not_contact is True
    assert lead.next_follow_up_at is None

    resumed_result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=3001,
            telegram_chat_id=3001,
            username="stop_user",
            full_name="Stop User",
            text="Здравствуйте, снова актуально",
            channel=MessageChannel.API_SIMULATION,
        )
    )
    lead = LeadRepository(db_session).get(stop_result.lead_id)

    assert resumed_result.stage == LeadStage.ENGAGED
    assert lead is not None
    assert lead.do_not_contact is False
    assert lead.next_follow_up_at is None
