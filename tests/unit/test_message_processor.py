from decimal import Decimal

from app.ai.contracts import AnalyzerContext, AnalyzerResult
from app.core.enums import IntentType, LeadStage, MessageChannel
from app.db.models.service import Service
from app.repositories.leads import LeadRepository
from app.services.message_processor import IncomingMessageDTO, MessageProcessor


class DummyAnalyzer:
    model_name = "dummy"

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        return AnalyzerResult(
            intent=IntentType.SERVICE_QUESTION,
            stage=LeadStage.QUALIFIED,
            reply_text="Подберу решение, расскажите подробнее о процессе.",
            confidence=0.77,
            raw={"provider": "dummy"},
        )


def test_message_processor_creates_lead_extracts_contacts_and_prepends_intro(db_session) -> None:
    db_session.add(
        Service(
            name="AI Saller Alina — AI-менеджер по продажам",
            description="Описание",
            price_from=Decimal("50000.00"),
            currency="RUB",
            is_active=True,
        )
    )
    db_session.commit()

    processor = MessageProcessor(db_session, analyzer=DummyAnalyzer())
    result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=1001,
            telegram_chat_id=2001,
            username="test_user",
            full_name="Иван Тест",
            text="Здравствуйте, мой телефон +7 (999) 123-45-67 и email test@example.com",
            channel=MessageChannel.API_SIMULATION,
        )
    )

    lead = LeadRepository(db_session).get(result.lead_id)

    assert lead is not None
    assert lead.phone == "+79991234567"
    assert lead.email == "test@example.com"
    assert result.intent == IntentType.CONTACT_SHARING
    assert result.reply_text == "Подберу решение, расскажите подробнее о процессе."
    assert lead.follow_up_step == 0
    assert lead.next_follow_up_at is None
