from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
TIME_WITH_MINUTES_PATTERN = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
HOUR_ONLY_PATTERN = re.compile(r"(?:^|\s|в)\s*([01]?\d|2[0-3])\b")
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

PRICE_REQUEST_HINTS = ("цена", "стоимость", "сколько стоит", "прайс", "цены")
PRICE_REPLY_HINTS = ("120000", "120 000", "стоимость", "цена")
AFFIRMATIVE_HINTS = ("да", "давайте", "ок", "хорошо", "согласен", "согласна", "подходит")
UNKNOWN_ANSWER_HINTS = ("не знаю", "откуда знаю", "сложно сказать", "без понятия")

QUALIFICATION_FLOW: tuple[tuple[str, str], ...] = (
    ("lead_source", "Откуда к вам обычно приходят заявки?"),
    ("monthly_leads", "Сколько заявок примерно приходит в месяц?"),
    ("avg_ticket", "Какой у вас средний чек?"),
    ("response_time", "Как быстро вы обычно отвечаете клиентам?"),
    ("lost_dialogs", "Сколько заявок примерно теряется из-за пропущенных ответов или незавершенных диалогов?"),
)

PRIORITY_QUESTION = (
    "Что для вас сейчас важнее: не терять заявки, увеличить количество записей "
    "или полностью автоматизировать общение с клиентами?"
)


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
            qualification_data=self._qualification_for_ai(lead.qualification_data or {}),
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

        normalized_collected = self._normalize_collected_data(ai_result.collected_data)
        extracted_from_text = self._extract_qualification_from_text(
            text=dto.text,
            existing=lead.qualification_data or {},
        )
        lead.qualification_data = self._merge_qualification_data(
            existing=lead.qualification_data or {},
            collected={**normalized_collected, **extracted_from_text},
            contacts=contacts,
        )

        final_stage = LeadStagePolicy.resolve(current=lead.stage, proposed=ai_result.stage)
        reply_text = ai_result.reply_text
        reply_text, final_stage, asked_key = self._apply_guided_funnel(
            user_text=dto.text,
            intent=ai_result.intent,
            current_stage=lead.stage,
            proposed_stage=final_stage,
            qualification_data=lead.qualification_data,
            ai_reply=reply_text,
        )
        self._set_last_question_key(lead.qualification_data, asked_key)

        had_confirmed_booking = lead.booking_slot_at is not None
        booked_slot = self._resolve_booking_slot(
            ai_selected_slot=ai_result.selected_slot,
            user_text=dto.text,
            available_slots=available_slots,
            now_utc=now_utc,
            allow_text_fallback=ai_result.intent in {IntentType.BOOKING_INTENT, IntentType.READY_TO_BUY},
        )
        booking_confirmed = booked_slot is not None
        if booking_confirmed:
            final_stage = LeadStage.BOOKED
            lead.booking_slot_at = booked_slot.astimezone(UTC)
        elif final_stage == LeadStage.BOOKED and not had_confirmed_booking:
            final_stage = LeadStage.BOOKING_PENDING

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
        self._reset_follow_up_schedule(lead, now_utc, channel=dto.channel)

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
        # Explicit /start means a fresh dialogue run.
        # Do not preserve terminal BOOKED state from previous sessions.
        final_stage = LeadStage.ENGAGED
        lead.stage = final_stage
        lead.last_intent = IntentType.GREETING
        lead.do_not_contact = False
        lead.stopped_at = None
        lead.booking_slot_at = None
        lead.handoff_requested = False
        lead.qualification_data = {}
        lead.last_bot_message_at = now_utc
        self._reset_follow_up_schedule(lead, now_utc, channel=channel)

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

    def _reset_follow_up_schedule(self, lead: Lead, now_utc: datetime, *, channel: MessageChannel) -> None:
        if channel != MessageChannel.TELEGRAM:
            lead.follow_up_step = 0
            lead.next_follow_up_at = None
            return

        if lead.do_not_contact or lead.stage in {LeadStage.BOOKED, LeadStage.LOST}:
            lead.follow_up_step = 0
            lead.next_follow_up_at = None
            return

        lead.follow_up_step = 0
        lead.next_follow_up_at = schedule_follow_up_at(now_utc, 1)

    def _apply_guided_funnel(
        self,
        *,
        user_text: str,
        intent: IntentType,
        current_stage: LeadStage,
        proposed_stage: LeadStage,
        qualification_data: dict,
        ai_reply: str,
    ) -> tuple[str, LeadStage, str | None]:
        text = user_text.lower()
        price_requested = self._is_price_requested(text) or intent == IntentType.PRICE_QUESTION
        booking_requested = intent in {IntentType.BOOKING_INTENT, IntentType.READY_TO_BUY}

        if price_requested or booking_requested:
            return ai_reply, proposed_stage, None

        if self._mentions_price(ai_reply):
            ai_reply = "Поняла. Сначала коротко разберу вашу ситуацию, чтобы дать точную рекомендацию."

        next_question = self._next_missing_qualification_question(qualification_data)
        if current_stage in {LeadStage.NEW, LeadStage.ENGAGED, LeadStage.QUALIFIED} and next_question is not None:
            key, question = next_question
            stage = LeadStage.ENGAGED if self._qualification_score(qualification_data) < 3 else LeadStage.QUALIFIED
            return question, stage, key

        if current_stage in {LeadStage.ENGAGED, LeadStage.QUALIFIED}:
            return self._build_offer_bridge(qualification_data), LeadStage.INTERESTED, "priority"

        if proposed_stage == LeadStage.INTERESTED and self._is_affirmative(text):
            return self._build_offer_bridge(qualification_data), LeadStage.INTERESTED, "priority"

        return ai_reply, proposed_stage, None

    def _qualification_for_ai(self, data: dict) -> dict:
        return {str(k): v for k, v in data.items() if not str(k).startswith("_")}

    def _set_last_question_key(self, data: dict, key: str | None) -> None:
        if key:
            data["_last_question_key"] = key
            return
        data.pop("_last_question_key", None)

    def _normalize_collected_data(self, collected: dict[str, str | int | float]) -> dict[str, str | int | float]:
        normalized: dict[str, str | int | float] = {}
        aliases = {
            "lead_source": {"lead_source", "source", "traffic_source", "источник", "канал"},
            "monthly_leads": {"monthly_leads", "leads_per_month", "requests_per_month", "заявки_в_месяц"},
            "avg_ticket": {"avg_ticket", "average_ticket", "average_check", "средний_чек"},
            "response_time": {"response_time", "reply_speed", "response_speed", "скорость_ответа"},
            "lost_dialogs": {"lost_dialogs", "lost_leads", "losses", "потери"},
            "priority": {"priority", "main_priority", "приоритет"},
        }
        for key, value in collected.items():
            key_lower = str(key).lower()
            target = None
            for canonical, keys in aliases.items():
                if key_lower in keys:
                    target = canonical
                    break
            if target is None:
                continue
            normalized[target] = value
        return normalized

    def _extract_qualification_from_text(self, *, text: str, existing: dict) -> dict[str, str | int | float]:
        lowered = text.lower()
        extracted: dict[str, str | int | float] = {}

        last_key = str(existing.get("_last_question_key") or "")
        if last_key and any(hint in lowered for hint in UNKNOWN_ANSWER_HINTS):
            extracted[last_key] = "неизвестно"

        channels = [name for name in ("telegram", "instagram", "инстаграм", "сайт", "авито", "vk", "вк", "tiktok") if name in lowered]
        if channels:
            extracted["lead_source"] = ", ".join(dict.fromkeys(channels))

        monthly_match = re.search(r"(\d{1,5})\s*(?:заяв|лид)", lowered)
        if monthly_match:
            extracted["monthly_leads"] = int(monthly_match.group(1))

        if "средний чек" in lowered or "чек" in lowered:
            ticket_match = re.search(r"(\d[\d\s]{1,12})(?:\s*(?:руб|₽|тыс|млн))?", lowered)
            if ticket_match:
                extracted["avg_ticket"] = re.sub(r"\s+", "", ticket_match.group(1))

        if "отвеч" in lowered:
            response_match = re.search(r"(\d+)\s*(минут|мин|час|часа|часов|ч)", lowered)
            if response_match:
                extracted["response_time"] = f"{response_match.group(1)} {response_match.group(2)}"

        if "теря" in lowered or "пропада" in lowered or "не довод" in lowered:
            lost_match = re.search(r"(\d{1,4})\s*%?", lowered)
            extracted["lost_dialogs"] = lost_match.group(1) if lost_match else "есть потери"

        if "не терять" in lowered:
            extracted["priority"] = "не терять заявки"
        elif "запис" in lowered:
            extracted["priority"] = "увеличить записи"
        elif "автомат" in lowered:
            extracted["priority"] = "полная автоматизация"

        return extracted

    def _next_missing_qualification_question(self, data: dict) -> tuple[str, str] | None:
        for key, question in QUALIFICATION_FLOW:
            value = data.get(key)
            if value is None:
                return key, question
            if isinstance(value, str) and not value.strip():
                return key, question
        if not data.get("priority"):
            return "priority", PRIORITY_QUESTION
        return None

    def _qualification_score(self, data: dict) -> int:
        score = 0
        for key, _ in QUALIFICATION_FLOW:
            value = data.get(key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            score += 1
        return score

    def _build_offer_bridge(self, qualification_data: dict) -> str:
        monthly = qualification_data.get("monthly_leads")
        losses = qualification_data.get("lost_dialogs")

        summary_bits: list[str] = []
        if monthly:
            summary_bits.append(f"у вас около {monthly} заявок в месяц")
        if losses:
            summary_bits.append("часть диалогов теряется")

        summary = ""
        if summary_bits:
            summary = "Поняла, " + " и ".join(summary_bits) + ". "

        return (
            summary
            + "В такой ситуации AI-менеджер может быстро отвечать, не терять диалоги и доводить клиентов до консультации. "
            + PRIORITY_QUESTION
        )

    def _is_price_requested(self, text: str) -> bool:
        return any(hint in text for hint in PRICE_REQUEST_HINTS)

    def _mentions_price(self, text: str) -> bool:
        lowered = text.lower()
        return any(hint in lowered for hint in PRICE_REPLY_HINTS)

    def _is_affirmative(self, text: str) -> bool:
        return any(re.search(rf"(?:^|\s){re.escape(token)}(?:$|[!,.?\s])", text) for token in AFFIRMATIVE_HINTS)

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

    def _resolve_booking_slot(
        self,
        *,
        ai_selected_slot: str | None,
        user_text: str,
        available_slots: list[str],
        now_utc: datetime,
        allow_text_fallback: bool,
    ) -> datetime | None:
        by_ai = self._resolve_selected_slot(ai_selected_slot, available_slots, now_utc)
        if by_ai is not None:
            return by_ai
        if not allow_text_fallback:
            return None
        return self._resolve_slot_from_user_text(user_text=user_text, now_utc=now_utc)

    def _resolve_slot_from_user_text(self, *, user_text: str, now_utc: datetime) -> datetime | None:
        text = user_text.lower()
        now_msk = now_utc.astimezone(MOSCOW_TZ)

        day_offset = 0
        if "послезавтра" in text:
            day_offset = 2
        elif "завтра" in text:
            day_offset = 1
        elif "сегодня" in text:
            day_offset = 0

        hour: int | None = None
        minute: int | None = None

        match_full = TIME_WITH_MINUTES_PATTERN.search(text)
        if match_full:
            hour = int(match_full.group(1))
            minute = int(match_full.group(2))
        else:
            match_hour = HOUR_ONLY_PATTERN.search(text)
            if match_hour:
                hour = int(match_hour.group(1))
                minute = 0

        if hour is None or minute is None:
            return None

        candidate_date = (now_msk + timedelta(days=day_offset)).date()
        candidate_slot = datetime(
            year=candidate_date.year,
            month=candidate_date.month,
            day=candidate_date.day,
            hour=hour,
            minute=minute,
            tzinfo=MOSCOW_TZ,
        )

        if not is_valid_consultation_slot(candidate_slot, now_utc=now_utc):
            return None

        return candidate_slot

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
