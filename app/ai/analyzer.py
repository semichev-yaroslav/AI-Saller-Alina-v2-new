import json
import logging
import time
from collections.abc import Iterable
from typing import Protocol

from openai import OpenAI

from app.ai.contracts import AnalyzerContext, AnalyzerResult
from app.ai.prompt_builder import build_system_prompt, build_user_prompt
from app.core.config import get_settings
from app.core.enums import IntentType, LeadStage

logger = logging.getLogger(__name__)


class LeadAnalyzer(Protocol):
    model_name: str

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        ...


class HeuristicLeadAnalyzer:
    model_name = "heuristic-v1"

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        text = message_text.lower()
        intent = self._detect_intent(text)
        stage = self._detect_stage(intent, context.current_stage)
        reply = self._build_reply(intent, context.services)

        return AnalyzerResult(
            intent=intent,
            stage=stage,
            reply_text=reply,
            confidence=0.62,
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
        if current_stage in {LeadStage.BOOKED, LeadStage.LOST}:
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

    def _build_reply(self, intent: IntentType, services: list[dict[str, str]]) -> str:
        service_names = [item.get("name", "") for item in services if item.get("name")]

        if intent == IntentType.PRICE_QUESTION:
            priced = []
            for srv in services:
                name = srv.get("name")
                price = srv.get("price_from")
                currency = srv.get("currency")
                if name and price:
                    priced.append(f"{name}: от {price} {currency or ''}".strip())
            if priced:
                return "Вот актуальные стартовые цены: " + "; ".join(priced) + ". Что из этого ближе к вашей задаче?"
            return "Точные цены зависят от объема работ. Опишите задачу, и я предложу релевантный вариант с оценкой."

        if intent == IntentType.READY_TO_BUY:
            return (
                "Отлично, зафиксировал интерес к покупке. Напишите удобные контакты и желаемое время созвона, "
                "чтобы перейти к следующему шагу."
            )

        if intent == IntentType.BOOKING_INTENT:
            return "Готов организовать бронь. Укажите удобную дату, время и контакт для подтверждения."

        if intent == IntentType.OBJECTION:
            return (
                "Понимаю сомнения. Давайте уточним, что для вас критично: бюджет, сроки или функционал. "
                "Под это предложу оптимальный формат."
            )

        if intent == IntentType.SERVICE_QUESTION:
            listed = ", ".join(service_names[:4]) if service_names else "AI-решения под задачи бизнеса"
            return (
                f"Я Алина, менеджер по продажам AI-решений. Можем предложить: {listed}. "
                "Что для вас приоритетно: обработка заявок, воронка продаж, прогрев или интеграция с CRM?"
            )

        if intent == IntentType.CONTACT_SHARING:
            return "Контакты получил. Подскажите, какую задачу хотите автоматизировать в первую очередь?"

        if intent == IntentType.GREETING:
            return (
                "Здравствуйте. Я Алина, менеджер по продажам по внедрению AI в бизнес-процессы. "
                "Опишите вашу задачу, и я помогу подобрать подходящий формат внедрения."
            )

        return "Уточните, пожалуйста, вашу цель: продажи, поддержка, обработка заявок или база знаний?"


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
