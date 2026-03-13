from decimal import Decimal

from app.ai.contracts import AnalyzerContext, AnalyzerResult
from app.core.enums import IntentType, LeadStage, MessageChannel
from app.db.models.lead import Lead
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


class PriceJumpAnalyzer:
    model_name = "price-jump"

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        return AnalyzerResult(
            intent=IntentType.SERVICE_QUESTION,
            stage=LeadStage.INTERESTED,
            reply_text="Стоимость внедрения 120000 рублей. Хотите консультацию?",
            confidence=0.91,
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
    assert result.reply_text == "Откуда к вам обычно приходят заявки?"
    assert lead.follow_up_step == 0
    assert lead.next_follow_up_at is None


def test_guided_funnel_prevents_price_jump_on_affirmative(db_session) -> None:
    lead = Lead(
        telegram_user_id=777001,
        telegram_chat_id=777001,
        username="price_jump_user",
        full_name="Price Jump",
        stage=LeadStage.QUALIFIED,
        qualification_data={
            "lead_source": "telegram",
            "monthly_leads": 100,
            "avg_ticket": "70000",
            "response_time": "5 минут",
            "lost_dialogs": "неизвестно",
        },
    )
    db_session.add(lead)
    db_session.commit()

    processor = MessageProcessor(db_session, analyzer=PriceJumpAnalyzer())
    result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=777001,
            telegram_chat_id=777001,
            username="price_jump_user",
            full_name="Price Jump",
            text="Давайте",
            channel=MessageChannel.API_SIMULATION,
        )
    )

    assert "120000" not in result.reply_text
    assert "Что для вас сейчас важнее" in result.reply_text
    assert result.stage == LeadStage.QUALIFIED


def test_guided_funnel_allows_price_when_user_asks_directly(db_session) -> None:
    lead = Lead(
        telegram_user_id=777002,
        telegram_chat_id=777002,
        username="price_question_user",
        full_name="Price Question",
        stage=LeadStage.ENGAGED,
        qualification_data={"lead_source": "сайт"},
    )
    db_session.add(lead)
    db_session.commit()

    processor = MessageProcessor(db_session, analyzer=PriceJumpAnalyzer())
    result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=777002,
            telegram_chat_id=777002,
            username="price_question_user",
            full_name="Price Question",
            text="Какая цена внедрения?",
            channel=MessageChannel.API_SIMULATION,
        )
    )

    assert "120000" in result.reply_text
    assert result.stage == LeadStage.INTERESTED
