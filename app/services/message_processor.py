import logging
import re
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.analyzer import HeuristicLeadAnalyzer, LeadAnalyzer, build_default_analyzer, serialize_services_for_ai
from app.ai.contracts import AnalyzerContext
from app.ai.prompt_builder import PROMPT_VERSION, build_first_touch_intro, build_start_funnel_intro
from app.core.config import get_settings
from app.core.enums import AIRunStatus, DeliveryStatus, IntentType, LeadStage, MessageChannel, MessageSource
from app.db.models.message import Message
from app.repositories.ai_runs import AIRunRepository
from app.repositories.leads import LeadRepository
from app.repositories.messages import MessageRepository
from app.repositories.services import ServiceRepository
from app.services.contact_extractor import extract_contacts
from app.services.stage_policy import LeadStagePolicy

logger = logging.getLogger(__name__)
START_COMMAND_PATTERN = re.compile(r"^/start(?:@[\w_]+)?(?:\s+.*)?$", flags=re.IGNORECASE)
TELEGRAM_SEND_ATTEMPTS = 3


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
            extra={
                "telegram_user_id": dto.telegram_user_id,
                "channel": dto.channel.value,
            },
        )

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

        if self._is_start_command(dto.text):
            return self._handle_start_scenario(
                lead=lead,
                incoming_message=incoming_message,
                channel=dto.channel,
            )

        contacts = extract_contacts(dto.text)
        self.leads_repo.update_contact_info(lead, phone=contacts.get("phone"), email=contacts.get("email"))

        context_messages = self.messages_repo.get_recent_for_context(
            lead.id,
            limit=self.settings.history_window_messages,
        )
        services = self.services_repo.list_active()

        analyzer_context = AnalyzerContext(
            current_stage=lead.stage,
            history=[
                {
                    "role": msg.source.value,
                    "text": msg.text,
                }
                for msg in context_messages
            ],
            services=serialize_services_for_ai(services),
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

        final_stage = LeadStagePolicy.resolve(current=lead.stage, proposed=ai_result.stage)

        reply_text = ai_result.reply_text
        if ai_result.intent in {IntentType.OBJECTION, IntentType.UNCLEAR} and ai_result.confidence < 0.7:
            reply_text = (
                f"{reply_text}\n\n"
                "Если хотите, могу сразу подключить менеджера для точной консультации по вашему кейсу."
            )
        if is_new_lead:
            first_touch = build_first_touch_intro([srv.name for srv in services])
            reply_text = f"{first_touch}\n\n{reply_text}"

        lead.stage = final_stage
        lead.last_intent = ai_result.intent

        ai_run = self.ai_runs_repo.create(
            lead_id=lead.id,
            input_message_id=incoming_message.id,
            model=self.analyzer.model_name,
            prompt_version=PROMPT_VERSION,
            intent=ai_result.intent,
            predicted_stage=final_stage,
            confidence=ai_result.confidence,
            reply_text=reply_text,
            raw_response=ai_result.raw,
            latency_ms=ai_result.raw.get("latency_ms") if isinstance(ai_result.raw, dict) else None,
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

        logger.info(
            "Message processed",
            extra={
                "lead_id": lead.id,
                "intent": ai_result.intent.value,
                "stage": final_stage.value,
                "ai_run_id": ai_run.id,
            },
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

    def _is_start_command(self, text: str) -> bool:
        return bool(START_COMMAND_PATTERN.match(text.strip()))

    def _handle_start_scenario(
        self,
        *,
        lead,
        incoming_message: Message,
        channel: MessageChannel,
    ) -> ProcessResult:
        services = self.services_repo.list_active()
        reply_text = build_start_funnel_intro([srv.name for srv in services])

        final_stage = LeadStagePolicy.resolve(current=lead.stage, proposed=LeadStage.ENGAGED)
        lead.stage = final_stage
        lead.last_intent = IntentType.GREETING

        self.ai_runs_repo.create(
            lead_id=lead.id,
            input_message_id=incoming_message.id,
            model="rule-start-v1",
            prompt_version=f"{PROMPT_VERSION}-start",
            intent=IntentType.GREETING,
            predicted_stage=final_stage,
            confidence=0.99,
            reply_text=reply_text,
            raw_response={
                "provider": "rule_engine",
                "scenario": "telegram_start",
                "services_count": len(services),
            },
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
