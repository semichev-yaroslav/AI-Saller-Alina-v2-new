from decimal import Decimal

from app.ai.contracts import AnalyzerContext, AnalyzerResult
from app.core.enums import DeliveryStatus, IntentType, LeadStage, MessageChannel
from app.db.models.message import Message
from app.db.models.service import Service
from app.services.message_processor import IncomingMessageDTO, MessageProcessor


class DummyAnalyzer:
    model_name = "dummy"

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        return AnalyzerResult(
            intent=IntentType.SERVICE_QUESTION,
            stage=LeadStage.QUALIFIED,
            reply_text="Расскажите подробнее о бизнес-процессе.",
            confidence=0.9,
            raw={"provider": "dummy"},
        )


class FlakySender:
    def __init__(self) -> None:
        self.calls = 0

    def send_message(self, chat_id: int, text: str) -> int:
        self.calls += 1
        if self.calls < 2:
            raise RuntimeError("temporary network error")
        return 777


def test_telegram_delivery_retries_and_marks_sent(db_session) -> None:
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

    sender = FlakySender()
    processor = MessageProcessor(db_session, analyzer=DummyAnalyzer(), telegram_sender=sender)

    result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=501,
            telegram_chat_id=601,
            username="retry_user",
            full_name="Retry User",
            text="Нужен AI менеджер",
            channel=MessageChannel.TELEGRAM,
            telegram_message_id=1,
            telegram_update_id=1,
        )
    )

    outgoing = db_session.get(Message, result.outgoing_message_id)

    assert sender.calls == 2
    assert outgoing is not None
    assert outgoing.delivery_status == DeliveryStatus.SENT
    assert outgoing.telegram_message_id == 777
