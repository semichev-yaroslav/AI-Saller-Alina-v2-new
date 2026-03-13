from app.ai.contracts import AnalyzerContext, AnalyzerResult
from app.core.enums import IntentType, LeadStage, MessageChannel
from app.db.models.lead import Lead
from app.services.message_processor import IncomingMessageDTO, MessageProcessor


class BookingAnalyzer:
    model_name = "booking-analyzer"

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        return AnalyzerResult(
            intent=IntentType.BOOKING_INTENT,
            stage=LeadStage.BOOKED,
            reply_text="Подтверждаю запись.",
            confidence=0.95,
            selected_slot="2099-12-31 11:00",
            raw={"provider": "dummy"},
        )


class BookingWithoutSlotAnalyzer:
    model_name = "booking-analyzer-no-slot"

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        return AnalyzerResult(
            intent=IntentType.BOOKING_INTENT,
            stage=LeadStage.BOOKING_PENDING,
            reply_text="Отлично, записала вас.",
            confidence=0.95,
            selected_slot=None,
            raw={"provider": "dummy"},
        )


class CaptureSender:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def send_message(self, chat_id: int, text: str) -> int:
        self.calls.append((chat_id, text))
        return len(self.calls)


def test_booking_marks_lead_booked_and_notifies_admin(db_session) -> None:
    sender = CaptureSender()
    processor = MessageProcessor(db_session, analyzer=BookingAnalyzer(), telegram_sender=sender)
    processor.settings.telegram_admin_chat_id = 999999

    result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=4501,
            telegram_chat_id=5501,
            username="book_user",
            full_name="Book User",
            text="Давайте завтра в 11:00",
            channel=MessageChannel.TELEGRAM,
            telegram_message_id=10,
            telegram_update_id=20,
        )
    )

    lead = db_session.get(Lead, result.lead_id)

    assert result.stage == LeadStage.BOOKED
    assert lead is not None
    assert lead.booking_slot_at is not None
    assert lead.next_follow_up_at is None

    # 1 - клиенту, 2 - админу.
    assert len(sender.calls) == 2
    assert sender.calls[0][0] == 5501
    assert sender.calls[1][0] == 999999
    assert "Новая запись на консультацию" in sender.calls[1][1]


def test_booking_can_be_parsed_from_user_text_when_llm_slot_missing(db_session) -> None:
    sender = CaptureSender()
    processor = MessageProcessor(db_session, analyzer=BookingWithoutSlotAnalyzer(), telegram_sender=sender)
    processor.settings.telegram_admin_chat_id = 999999

    result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=4601,
            telegram_chat_id=5601,
            username="book_user2",
            full_name="Book User 2",
            text="Давайте консультацию 31.12.2099 в 11:00",
            channel=MessageChannel.TELEGRAM,
            telegram_message_id=11,
            telegram_update_id=21,
        )
    )

    lead = db_session.get(Lead, result.lead_id)

    assert result.stage == LeadStage.BOOKED
    assert lead is not None
    assert lead.booking_slot_at is not None
    assert lead.next_follow_up_at is None
    assert len(sender.calls) == 2
