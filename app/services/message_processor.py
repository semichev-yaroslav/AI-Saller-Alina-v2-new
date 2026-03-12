from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.ai.analyzer import HeuristicLeadAnalyzer, LeadAnalyzer, build_default_analyzer, serialize_services_for_ai
from app.ai.contracts import AnalyzerContext
from app.ai.prompt_builder import PROMPT_VERSION, build_first_touch_intro, build_start_funnel_intro
from app.core.config import get_settings
from app.core.enums import AIRunStatus, DeliveryStatus, IntentType, LeadStage, MessageChannel, MessageSource
from app.db.models.lead import Lead
from app.db.models.message import Message
from app.repositories.ai_runs import AIRunRepository
from app.repositories.leads import LeadRepository
from app.repositories.messages import MessageRepository
from app.repositories.services import ServiceRepository
from app.services.contact_extractor import extract_contacts
from app.services.schedule import (
    MOSCOW_TZ,
    generate_consultation_slots,
    is_valid_consultation_slot,
    parse_slot,
    schedule_follow_up_at,
)
from app.services.stage_policy import LeadStagePolicy

logger = logging.getLogger(__name__)

START_COMMAND_PATTERN = re.compile(r"^/start(?:@[\w_]+)?(?:\s+.*)?$", flags=re.IGNORECASE)
TELEGRAM_SEND_ATTEMPTS = 3

STOP_PHRASES = (
    "не интересно",
    "неинтересно",
    "не пишите",
    "больше не пишите",
    "не беспокоить",
    "стоп",
    "хватит",
    "отпишись",
    "удалите номер",
    "удалите мой номер",
    "stop",
)

HANDOFF_HINTS = (
    "живой менеджер",
    "с менеджером",
    "оператор",
    "договор",
    "реквизиты",
    "коммерческое предложение",
)

STOP_REPLY_TEXT = "Понял, больше не буду писать.\nЕсли понадобится — напишите."
ADMIN_BOOKING_TITLE = "Новая запись на консультацию"
ADMIN_HANDOFF_TITLE = "Нужен живой менеджер"


class TelegramSender:
    def send_message(self, chat_id: int, text: str) -> int | None:
        raise NotImplementedError


@dataclass(slots=True)
class IncomingMessageDTO:
    telegram_user_id: int
    telegram_chat_id: int
    username: str | None
    full_name: str | None
    text: str
    channel: MessageChannel
    telegram_message_id: int | None = None
    telegram_update_id: int | None = None


@dataclass(slots=True)
class ProcessResult:
    lead_id: str
    incoming_message_id: str | None
    outgoing_message_id: str | None
    intent: IntentType
    stage: LeadStage
    confidence: float
    reply_text: str
    duplicate: bool = False


class MessageProcessor:
    def __init__(
        self,
        db: Session,
        *,
        analyzer: LeadAnalyzer | None = None,
        telegram_sender: TelegramSender | None = None,
    ) -> None:
        self.db = db
        self.settings = get_settings()
        self.leads_repo = LeadRepository(db)
        self.messages_repo = MessageRepository(db)
        self.services_repo = ServiceRepository(db)
        self.ai_runs_repo = AIRunRepository(db)

        self.analyzer = analyzer or build_default_analyzer()
        self.fallback_analyzer = HeuristicLeadAnalyzer()
        self.telegram_sender = telegram_sender

    def process(self, dto: IncomingMessageDTO) -> ProcessResult:
        logger.info(
            "Incoming message received",
            extra={"telegram_user_id": dto.telegram_user_id, "channel": dto.channel.value},
        )

        now_utc = datetime.now(UTC)

        lead, is_new_lead = self.leads_repo.create_or_update_from_telegram(
            telegram_user_id=dto.telegram_user_id,
            telegram_chat_id=dto.telegram_chat_id,
            username=dto.username,
            full_name=dto.full_name,
        )

        incoming_message, inserted = self.messages_repo.create_incoming_if_new(
            lead_id=lead.id,
            channel=dto.channel,
            text=dto.text,
            telegram_message_id=dto.telegram_message_id,
            telegram_update_id=dto.telegram_update_id,
        )

        if not inserted:
            logger.info("Duplicate update skipped", extra={"update_id": dto.telegram_update_id})
            existing_lead = self.leads_repo.get_by_telegram_user_id(dto.telegram_user_id)
            return ProcessResult(
                lead_id=existing_lead.id if existing_lead else lead.id,
                incoming_message_id=None,
                outgoing_message_id=None,
                intent=existing_lead.last_intent if existing_lead and existing_lead.last_intent else IntentType.UNCLEAR,
                stage=existing_lead.stage if existing_lead else LeadStage.NEW,
                confidence=0.0,
                reply_text="duplicate",
                duplicate=True,
            )

        lead.last_user_message_at = now_utc
        self._reactivate_if_needed(lead, dto.text)

        if self._is_stop_request(dto.text):
            return self._handle_stop_request(lead=lead, incoming_message=incoming_message, channel=dto.channel, now_utc=now_utc)

        if self._is_start_command(dto.text):
            return self._handle_start_scenario(
                lead=lead,
                incoming_message=incoming_message,
                channel=dto.channel,
                now_utc=now_utc,
            )

        contacts = extract_contacts(dto.text)
        self.leads_repo.update_contact_info(lead, phone=contacts.get("phone"), email=contacts.get("email"))

        context_messages = self.messages_repo.get_recent_for_context(lead.id, limit=self.settings.history_window_messages)
        services = self.services_repo.list_active()
        available_slots = generate_consultation_slots(now_utc, days_ahead=3, limit=8)

        analyzer_context = AnalyzerContext(
            current_stage=lead.stage,
            history=[{"role": msg.source.value, "text": msg.text} for msg in context_messages],
            services=serialize_services_for_ai(services),
            qualification_data=lead.qualification_data or {},
            available_slots=available_slots,
        )

        try:
            ai_result = self.analyzer.analyze(dto.text, analyzer_context)
            ai_status = AIRunStatus.SUCCESS
            ai_error = None
        except Exception as exc:  # noqa: BLE001
            logger.exception("AI analysis failed; using heuristic fallback")
            ai_result = self.fallback_analyzer.analyze(dto.text, analyzer_context)
            ai_status = AIRunStatus.ERROR
            ai_error = str(exc)

        if contacts.get("phone") or contacts.get("email"):
            ai_result.intent = IntentType.CONTACT_SHARING
            ai_result.confidence = max(ai_result.confidence, 0.85)

        lead.qualification_data = self._merge_qualification_data(
            existing=lead.qualification_data or {},
            collected=ai_result.collected_data,
            contacts=contacts,
        )

        final_stage = LeadStagePolicy.resolve(current=lead.stage, proposed=ai_result.stage)
        booked_slot = self._resolve_selected_slot(ai_result.selected_slot, available_slots, now_utc)
        booking_confirmed = booked_slot is not None
        if booking_confirmed:
            final_stage = LeadStage.BOOKED
            lead.booking_slot_at = booked_slot.astimezone(UTC)
        elif final_stage == LeadStage.BOOKED:
            final_stage = LeadStage.BOOKING_PENDING

        reply_text = ai_result.reply_text
        if booking_confirmed and booked_slot is not None:
            reply_text = self._build_booking_confirmation(booked_slot)
        elif is_new_lead and ai_result.intent in {IntentType.GREETING, IntentType.SERVICE_QUESTION, IntentType.UNCLEAR}:
            reply_text = build_first_touch_intro([srv.name for srv in services])
            ai_result.intent = IntentType.GREETING
            final_stage = LeadStage.ENGAGED
        elif ai_result.intent in {IntentType.OBJECTION, IntentType.UNCLEAR} and ai_result.confidence < 0.7:
            reply_text = f"{reply_text}\n\nЕсли хотите, могу подключить живого менеджера."

        handoff_needed = ai_result.handoff_to_admin or any(hint in dto.text.lower() for hint in HANDOFF_HINTS)
        if handoff_needed:
            lead.handoff_requested = True
            if "живого менеджера" not in reply_text.lower():
                reply_text = f"{reply_text}\n\nЕсли нужно, подключу живого менеджера."

        lead.stage = final_stage
        lead.last_intent = ai_result.intent
        lead.last_bot_message_at = now_utc
        self._reset_follow_up_schedule(lead, now_utc)

        raw_response = ai_result.raw if isinstance(ai_result.raw, dict) else {}
        ai_run = self.ai_runs_repo.create(
            lead_id=lead.id,
            input_message_id=incoming_message.id,
            model=self.analyzer.model_name,
            prompt_version=PROMPT_VERSION,
            intent=ai_result.intent,
            predicted_stage=final_stage,
            confidence=ai_result.confidence,
            reply_text=reply_text,
            raw_response=raw_response,
            latency_ms=raw_response.get("latency_ms"),
            status=ai_status,
            error_text=ai_error,
        )

        outgoing_status = DeliveryStatus.SENT
        if dto.channel == MessageChannel.TELEGRAM and self.telegram_sender is not None:
            outgoing_status = DeliveryStatus.PENDING

        outgoing_message = self.messages_repo.create(
            lead_id=lead.id,
            source=MessageSource.ASSISTANT,
            channel=dto.channel,
            text=reply_text,
            delivery_status=outgoing_status,
        )
        self.db.commit()

        if dto.channel == MessageChannel.TELEGRAM and self.telegram_sender is not None:
            self._send_to_telegram(lead.telegram_chat_id, outgoing_message)

        if booking_confirmed:
            self._notify_admin(self._build_admin_booking_message(lead, dto.text, booked_slot))
        elif handoff_needed:
            self._notify_admin(self._build_admin_handoff_message(lead, dto.text))

        logger.info(
            "Message processed",
            extra={"lead_id": lead.id, "intent": ai_result.intent.value, "stage": final_stage.value, "ai_run_id": ai_run.id},
        )

        return ProcessResult(
            lead_id=lead.id,
            incoming_message_id=incoming_message.id,
            outgoing_message_id=outgoing_message.id,
            intent=ai_result.intent,
            stage=final_stage,
            confidence=ai_result.confidence,
            reply_text=reply_text,
            duplicate=False,
        )

    def _send_to_telegram(self, chat_id: int, outgoing_message: Message) -> None:
        last_error: Exception | None = None

        for attempt in range(1, TELEGRAM_SEND_ATTEMPTS + 1):
            try:
                sent_message_id = self.telegram_sender.send_message(chat_id=chat_id, text=outgoing_message.text)
                outgoing_message.telegram_message_id = sent_message_id
                outgoing_message.delivery_status = DeliveryStatus.SENT
                outgoing_message.delivery_error = None
                self.db.commit()
                logger.info(
                    "Telegram reply sent",
                    extra={"chat_id": chat_id, "message_id": sent_message_id, "attempt": attempt},
                )
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "Telegram send attempt failed",
                    extra={"chat_id": chat_id, "attempt": attempt, "error": str(exc)},
                )
                if attempt < TELEGRAM_SEND_ATTEMPTS:
                    time.sleep(0.4 * attempt)

        logger.exception("Telegram send failed after retries", exc_info=last_error)
        outgoing_message.delivery_status = DeliveryStatus.FAILED
        outgoing_message.delivery_error = str(last_error) if last_error else "unknown send error"
        self.db.commit()

    def _notify_admin(self, message_text: str) -> None:
        if self.telegram_sender is None or self.settings.telegram_admin_chat_id is None:
            return

        for attempt in range(1, TELEGRAM_SEND_ATTEMPTS + 1):
            try:
                self.telegram_sender.send_message(chat_id=self.settings.telegram_admin_chat_id, text=message_text)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Admin telegram notification failed",
                    extra={"attempt": attempt, "error": str(exc)},
                )
                if attempt < TELEGRAM_SEND_ATTEMPTS:
                    time.sleep(0.4 * attempt)

    def _is_start_command(self, text: str) -> bool:
        return bool(START_COMMAND_PATTERN.match(text.strip()))

    def _is_stop_request(self, text: str) -> bool:
        lowered = text.lower().strip()
        return any(phrase in lowered for phrase in STOP_PHRASES)

    def _reactivate_if_needed(self, lead: Lead, text: str) -> None:
        if not lead.do_not_contact or self._is_stop_request(text):
            return

        lead.do_not_contact = False
        lead.stopped_at = None
        if lead.stage == LeadStage.LOST:
            lead.stage = LeadStage.ENGAGED
        logger.info("Lead reactivated after previous stop", extra={"lead_id": lead.id})

    def _handle_stop_request(
        self,
        *,
        lead: Lead,
        incoming_message: Message,
        channel: MessageChannel,
        now_utc: datetime,
    ) -> ProcessResult:
        lead.stage = LeadStage.LOST
        lead.last_intent = IntentType.OBJECTION
        lead.do_not_contact = True
        lead.stopped_at = now_utc
        lead.follow_up_step = 0
        lead.next_follow_up_at = None
        lead.last_bot_message_at = now_utc

        self.ai_runs_repo.create(
            lead_id=lead.id,
            input_message_id=incoming_message.id,
            model="rule-stop-v1",
            prompt_version=f"{PROMPT_VERSION}-stop",
            intent=IntentType.OBJECTION,
            predicted_stage=LeadStage.LOST,
            confidence=1.0,
            reply_text=STOP_REPLY_TEXT,
            raw_response={"provider": "rule_engine", "scenario": "stop_request"},
            latency_ms=0,
            status=AIRunStatus.SUCCESS,
            error_text=None,
        )

        outgoing_status = DeliveryStatus.SENT
        if channel == MessageChannel.TELEGRAM and self.telegram_sender is not None:
            outgoing_status = DeliveryStatus.PENDING

        outgoing_message = self.messages_repo.create(
            lead_id=lead.id,
            source=MessageSource.ASSISTANT,
            channel=channel,
            text=STOP_REPLY_TEXT,
            delivery_status=outgoing_status,
        )
        self.db.commit()

        if channel == MessageChannel.TELEGRAM and self.telegram_sender is not None:
            self._send_to_telegram(lead.telegram_chat_id, outgoing_message)

        return ProcessResult(
            lead_id=lead.id,
            incoming_message_id=incoming_message.id,
            outgoing_message_id=outgoing_message.id,
            intent=IntentType.OBJECTION,
            stage=LeadStage.LOST,
            confidence=1.0,
            reply_text=STOP_REPLY_TEXT,
            duplicate=False,
        )

    def _handle_start_scenario(
        self,
        *,
        lead: Lead,
        incoming_message: Message,
        channel: MessageChannel,
        now_utc: datetime,
    ) -> ProcessResult:
        services = self.services_repo.list_active()
        reply_text = build_start_funnel_intro([srv.name for srv in services])

        final_stage = LeadStagePolicy.resolve(current=lead.stage, proposed=LeadStage.ENGAGED)
        lead.stage = final_stage
        lead.last_intent = IntentType.GREETING
        lead.last_bot_message_at = now_utc
        self._reset_follow_up_schedule(lead, now_utc)

        self.ai_runs_repo.create(
            lead_id=lead.id,
            input_message_id=incoming_message.id,
            model="rule-start-v1",
            prompt_version=f"{PROMPT_VERSION}-start",
            intent=IntentType.GREETING,
            predicted_stage=final_stage,
            confidence=0.99,
            reply_text=reply_text,
            raw_response={"provider": "rule_engine", "scenario": "telegram_start", "services_count": len(services)},
            latency_ms=0,
            status=AIRunStatus.SUCCESS,
            error_text=None,
        )

        outgoing_status = DeliveryStatus.SENT
        if channel == MessageChannel.TELEGRAM and self.telegram_sender is not None:
            outgoing_status = DeliveryStatus.PENDING

        outgoing_message = self.messages_repo.create(
            lead_id=lead.id,
            source=MessageSource.ASSISTANT,
            channel=channel,
            text=reply_text,
            delivery_status=outgoing_status,
        )
        self.db.commit()

        if channel == MessageChannel.TELEGRAM and self.telegram_sender is not None:
            self._send_to_telegram(lead.telegram_chat_id, outgoing_message)

        logger.info("Start scenario processed", extra={"lead_id": lead.id, "stage": final_stage.value})

        return ProcessResult(
            lead_id=lead.id,
            incoming_message_id=incoming_message.id,
            outgoing_message_id=outgoing_message.id,
            intent=IntentType.GREETING,
            stage=final_stage,
            confidence=0.99,
            reply_text=reply_text,
            duplicate=False,
        )

    def _reset_follow_up_schedule(self, lead: Lead, now_utc: datetime) -> None:
        if lead.do_not_contact or lead.stage in {LeadStage.BOOKED, LeadStage.LOST}:
            lead.follow_up_step = 0
            lead.next_follow_up_at = None
            return

        lead.follow_up_step = 0
        lead.next_follow_up_at = schedule_follow_up_at(now_utc, 1)

    def _merge_qualification_data(
        self,
        *,
        existing: dict,
        collected: dict[str, str | int | float],
        contacts: dict[str, str | None],
    ) -> dict:
        merged = dict(existing)
        for key, value in collected.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            merged[key] = value
        if contacts.get("phone"):
            merged["phone"] = contacts["phone"]
        if contacts.get("email"):
            merged["email"] = contacts["email"]
        return merged

    def _resolve_selected_slot(
        self,
        selected_slot: str | None,
        available_slots: list[str],
        now_utc: datetime,
    ) -> datetime | None:
        if not selected_slot or selected_slot not in available_slots:
            return None
        parsed_slot = parse_slot(selected_slot)
        if parsed_slot is None:
            return None
        if not is_valid_consultation_slot(parsed_slot, now_utc=now_utc):
            return None
        return parsed_slot

    def _build_booking_confirmation(self, slot_msk: datetime) -> str:
        formatted = slot_msk.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")
        return f"Отлично, записала вас на консультацию {formatted} (МСК). Подтверждаю встречу."

    def _build_admin_booking_message(self, lead: Lead, incoming_text: str, slot_msk: datetime | None) -> str:
        slot_text = slot_msk.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M") if slot_msk else "не выбран"
        return (
            f"{ADMIN_BOOKING_TITLE}\n"
            f"Лид: {lead.full_name or '-'} (@{lead.username or '-'})\n"
            f"Telegram user id: {lead.telegram_user_id}\n"
            f"Telegram chat id: {lead.telegram_chat_id}\n"
            f"Слот: {slot_text} (МСК)\n"
            f"Телефон: {lead.phone or '-'}\n"
            f"Email: {lead.email or '-'}\n"
            f"Последнее сообщение: {incoming_text}"
        )

    def _build_admin_handoff_message(self, lead: Lead, incoming_text: str) -> str:
        return (
            f"{ADMIN_HANDOFF_TITLE}\n"
            f"Лид: {lead.full_name or '-'} (@{lead.username or '-'})\n"
            f"Telegram user id: {lead.telegram_user_id}\n"
            f"Telegram chat id: {lead.telegram_chat_id}\n"
            f"Стадия: {lead.stage.value}\n"
            f"Телефон: {lead.phone or '-'}\n"
            f"Email: {lead.email or '-'}\n"
            f"Сообщение клиента: {incoming_text}"
        )
