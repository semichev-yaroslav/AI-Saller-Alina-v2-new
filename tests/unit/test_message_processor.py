from decimal import Decimal
from pathlib import Path

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


class ContextCaptureAnalyzer:
    model_name = "capture"

    def __init__(self) -> None:
        self.last_history_size: int = 0
        self.last_company_knowledge: list[dict[str, str]] = []

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        self.last_history_size = len(context.history)
        self.last_company_knowledge = context.company_knowledge
        return AnalyzerResult(
            intent=IntentType.SERVICE_QUESTION,
            stage=LeadStage.ENGAGED,
            reply_text="Принято.",
            confidence=0.8,
            raw={"provider": "capture"},
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
    assert "где именно ai-менеджер может дать вам пользу" in result.reply_text.lower()
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


def test_context_window_uses_last_100_messages(db_session) -> None:
    analyzer = ContextCaptureAnalyzer()
    processor = MessageProcessor(db_session, analyzer=analyzer)
    processor.settings.history_window_messages = 100

    for index in range(70):
        processor.process(
            IncomingMessageDTO(
                telegram_user_id=880001,
                telegram_chat_id=880001,
                username="history_user",
                full_name="History User",
                text=f"Сообщение {index + 1}",
                channel=MessageChannel.API_SIMULATION,
            )
        )

    assert analyzer.last_history_size == 100


def test_context_includes_company_knowledge_from_files(db_session, tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "company"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    (knowledge_dir / "offer.md").write_text(
        "Мы внедряем AI-менеджера продаж для обработки заявок и записи на консультацию.",
        encoding="utf-8",
    )

    analyzer = ContextCaptureAnalyzer()
    processor = MessageProcessor(db_session, analyzer=analyzer)
    old_dir = processor.settings.company_knowledge_dir
    old_max_files = processor.settings.company_knowledge_max_files
    old_max_chars = processor.settings.company_knowledge_max_chars

    try:
        processor.settings.company_knowledge_dir = str(knowledge_dir)
        processor.settings.company_knowledge_max_files = 5
        processor.settings.company_knowledge_max_chars = 1000

        processor.process(
            IncomingMessageDTO(
                telegram_user_id=880002,
                telegram_chat_id=880002,
                username="knowledge_user",
                full_name="Knowledge User",
                text="Что вы продаете?",
                channel=MessageChannel.API_SIMULATION,
            )
        )
    finally:
        processor.settings.company_knowledge_dir = old_dir
        processor.settings.company_knowledge_max_files = old_max_files
        processor.settings.company_knowledge_max_chars = old_max_chars

    assert analyzer.last_company_knowledge
    assert "AI-менеджера продаж" in analyzer.last_company_knowledge[0]["content"]
