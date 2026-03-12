import json
import logging
import time
from collections.abc import Iterable
from typing import Protocol

from openai import OpenAI

from app.ai.contracts import AnalyzerContext, AnalyzerResult
from app.ai.prompt_builder import build_system_prompt, build_user_prompt
from app.core.config import get_settings
from app.core.enums import AssistantAction, IntentType, LeadStage

logger = logging.getLogger(__name__)


class LeadAnalyzer(Protocol):
    model_name: str

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        ...


class HeuristicLeadAnalyzer:
    model_name = "heuristic-v2"

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        text = message_text.lower()
        intent = self._detect_intent(text)
        stage = self._detect_stage(intent, context.current_stage)
        action = self._detect_action(intent)
        selected_slot = self._detect_selected_slot(text, context.available_slots)
        handoff_to_admin = self._needs_handoff(text)
        if selected_slot:
            stage = LeadStage.BOOKED
        reply = self._build_reply(intent, context.services, context.available_slots, selected_slot)

        return AnalyzerResult(
            intent=intent,
            stage=stage,
            reply_text=reply,
            confidence=0.62,
            action=action,
            selected_slot=selected_slot,
            handoff_to_admin=handoff_to_admin,
            raw={"provider": "heuristic"},
        )

    def _detect_intent(self, text: str) -> IntentType:
        if any(x in text for x in ["цена", "стоимость", "сколько стоит", "прайс"]):
            return IntentType.PRICE_QUESTION
        if any(x in text for x in ["хочу купить", "готов купить", "оплатить", "беру"]):
            return IntentType.READY_TO_BUY
        if any(x in text for x in ["созвон", "звонок", "встреч", "бронь", "забронировать"]):
            return IntentType.BOOKING_INTENT
        if any(x in text for x in ["дорого", "не подходит", "сомневаюсь", "не уверен", "возраж"]):
            return IntentType.OBJECTION
        if any(x in text for x in ["привет", "здравствуйте", "добрый", "hello", "hi"]):
            return IntentType.GREETING
        if any(x in text for x in ["бот", "ассистент", "заявок", "поддержк", "услуг", "что уме"]):
            return IntentType.SERVICE_QUESTION
        if any(x in text for x in ["@", "+7", "телефон", "почта", "email"]):
            return IntentType.CONTACT_SHARING
        return IntentType.UNCLEAR

    def _detect_stage(self, intent: IntentType, current_stage: LeadStage) -> LeadStage:
        if current_stage == LeadStage.BOOKED:
            return current_stage

        mapping = {
            IntentType.GREETING: LeadStage.ENGAGED,
            IntentType.SERVICE_QUESTION: LeadStage.QUALIFIED,
            IntentType.PRICE_QUESTION: LeadStage.INTERESTED,
            IntentType.OBJECTION: LeadStage.ENGAGED,
            IntentType.READY_TO_BUY: LeadStage.BOOKING_PENDING,
            IntentType.BOOKING_INTENT: LeadStage.BOOKING_PENDING,
            IntentType.CONTACT_SHARING: LeadStage.QUALIFIED,
            IntentType.UNCLEAR: LeadStage.ENGAGED,
        }
        return mapping.get(intent, current_stage)

    def _detect_action(self, intent: IntentType) -> AssistantAction:
        if intent == IntentType.BOOKING_INTENT:
            return AssistantAction.OFFER_CONSULTATION
        if intent in {IntentType.SERVICE_QUESTION, IntentType.GREETING, IntentType.UNCLEAR}:
            return AssistantAction.ASK_QUESTION
        if intent == IntentType.OBJECTION:
            return AssistantAction.HANDOFF
        return AssistantAction.REPLY

    def _needs_handoff(self, text: str) -> bool:
        handoff_keywords = (
            "живой менеджер",
            "с менеджером",
            "оператор",
            "договор",
            "реквизиты",
            "коммерческое предложение",
        )
        return any(keyword in text for keyword in handoff_keywords)

    def _detect_selected_slot(self, text: str, available_slots: list[str]) -> str | None:
        for slot in available_slots:
            normalized_slot = slot.lower().replace("t", " ")
            if normalized_slot in text:
                return slot
            date_part = normalized_slot.split(" ")[0]
            time_part = normalized_slot.split(" ")[1][:5] if " " in normalized_slot else ""
            if date_part in text and time_part and time_part in text:
                return slot
            if time_part and time_part in text and any(x in text for x in ["завтра", "сегодня"]):
                return slot
        return None

    def _build_reply(
        self,
        intent: IntentType,
        services: list[dict[str, str]],
        available_slots: list[str],
        selected_slot: str | None,
    ) -> str:
        service_names = [item.get("name", "") for item in services if item.get("name")]

        if intent == IntentType.PRICE_QUESTION:
            return (
                "Стоимость внедрения AI-менеджера фиксированная: 120 000 рублей. "
                "Скажите, какой результат для вас сейчас важнее: не терять заявки или увеличить записи на консультацию?"
            )

        if intent == IntentType.READY_TO_BUY:
            return (
                "Отлично, тогда предлагаю короткую консультацию на 30 минут. "
                "Какое время вам удобнее?"
            )

        if intent == IntentType.BOOKING_INTENT:
            if selected_slot:
                return f"Отлично, зафиксировала консультацию на {selected_slot}. Подтверждаю запись."
            if available_slots:
                options = ", ".join(available_slots[:2])
                return f"Могу предложить ближайшие окна: {options}. Какой вариант вам удобнее?"
            return "Готова подобрать время консультации. Какой день и время вам удобно?"

        if intent == IntentType.OBJECTION:
            return (
                "Понимаю. Давайте разберем ваш кейс на короткой консультации и покажу, где вы сможете сохранить заявки. "
                "Удобно?"
            )

        if intent == IntentType.SERVICE_QUESTION:
            listed = ", ".join(service_names[:4]) if service_names else "AI-решения под задачи бизнеса"
            return (
                f"Я Алина, менеджер по продажам. Для бизнеса обычно внедряют: {listed}. "
                "Скажите, откуда к вам обычно приходят заявки?"
            )

        if intent == IntentType.CONTACT_SHARING:
            return "Контакты получила. Скажите, сколько заявок примерно приходит в месяц?"

        if intent == IntentType.GREETING:
            return (
                "Привет. Я Алина, менеджер по продажам. "
                "Скажите, чем занимается ваш бизнес?"
            )

        return "Правильно понимаю, вам важно не терять заявки и быстрее отвечать клиентам?"


class OpenAILeadAnalyzer:
    def __init__(self) -> None:
        settings = get_settings()
        self.model_name = settings.openai_model
        self._temperature = settings.openai_temperature
        self._timeout = settings.openai_timeout_sec
        self._client = OpenAI(api_key=settings.openai_api_key)

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        start = time.perf_counter()
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(
            message_text=message_text,
            current_stage=context.current_stage.value,
            history=context.history,
            services=context.services,
            qualification_data=context.qualification_data,
            available_slots=context.available_slots,
        )

        response = self._client.chat.completions.create(
            model=self.model_name,
            temperature=self._temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=self._timeout,
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        content = response.choices[0].message.content or "{}"
        payload = self._safe_load_json(content)

        intent = self._to_intent(payload.get("intent"))
        stage = self._to_stage(payload.get("stage"), fallback=context.current_stage)
        reply_text = str(payload.get("reply_text") or "Уточните, пожалуйста, ваш запрос.").strip()
        confidence = self._to_confidence(payload.get("confidence"))
        action = self._to_action(payload.get("action"))
        collected_data = self._to_collected_data(payload.get("collected_data"))
        selected_slot = self._to_selected_slot(payload.get("selected_slot"), context.available_slots)
        handoff_to_admin = bool(payload.get("handoff_to_admin"))

        raw = {
            "provider": "openai",
            "latency_ms": elapsed_ms,
            "payload": payload,
            "model": response.model,
            "usage": response.usage.model_dump() if response.usage else None,
        }

        logger.info("AI analyzed message", extra={"intent": intent.value, "stage": stage.value, "latency_ms": elapsed_ms})

        return AnalyzerResult(
            intent=intent,
            stage=stage,
            reply_text=reply_text,
            confidence=confidence,
            action=action,
            collected_data=collected_data,
            selected_slot=selected_slot,
            handoff_to_admin=handoff_to_admin,
            raw=raw,
        )

    def _safe_load_json(self, content: str) -> dict:
        try:
            loaded = json.loads(content)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            logger.warning("OpenAI returned non-JSON content")
        return {}

    def _to_intent(self, value: object) -> IntentType:
        try:
            return IntentType(str(value))
        except ValueError:
            return IntentType.UNCLEAR

    def _to_stage(self, value: object, fallback: LeadStage) -> LeadStage:
        try:
            return LeadStage(str(value))
        except ValueError:
            return fallback

    def _to_confidence(self, value: object) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, numeric))

    def _to_action(self, value: object) -> AssistantAction:
        try:
            return AssistantAction(str(value))
        except ValueError:
            return AssistantAction.REPLY

    def _to_collected_data(self, value: object) -> dict[str, str | int | float]:
        if not isinstance(value, dict):
            return {}
        data: dict[str, str | int | float] = {}
        for key, raw_value in value.items():
            if isinstance(raw_value, (str, int, float)):
                data[str(key)] = raw_value
        return data

    def _to_selected_slot(self, value: object, available_slots: list[str]) -> str | None:
        if not isinstance(value, str):
            return None
        slot = value.strip()
        if not slot:
            return None
        return slot if slot in available_slots else None


def build_default_analyzer() -> LeadAnalyzer:
    settings = get_settings()
    if settings.openai_api_key:
        logger.info("Using OpenAI analyzer", extra={"model": settings.openai_model})
        return OpenAILeadAnalyzer()

    logger.warning("OPENAI_API_KEY is not set; fallback to heuristic analyzer")
    return HeuristicLeadAnalyzer()


def serialize_services_for_ai(services: Iterable) -> list[dict[str, str]]:
    data: list[dict[str, str]] = []
    for srv in services:
        price_from = srv.price_from
        data.append(
            {
                "name": srv.name,
                "description": srv.description,
                "price_from": str(price_from) if price_from is not None else "",
                "currency": srv.currency or "",
            }
        )
    return data
