import json
import logging
import time
from collections.abc import Iterable
from typing import Any, Protocol

from openai import OpenAI

from app.ai.contracts import AnalyzerContext, AnalyzerResult
from app.ai.prompt_builder import (
    build_response_writer_system_prompt,
    build_response_writer_user_prompt,
    build_state_extractor_system_prompt,
    build_state_extractor_user_prompt,
    build_strategy_system_prompt,
    build_strategy_user_prompt,
)
from app.core.config import get_settings
from app.core.enums import AssistantAction, IntentType, LeadStage
from app.services.business_case import BusinessCaseCalculator
from app.services.company_knowledge import retrieve_company_knowledge
from app.services.schedule import parse_slot

logger = logging.getLogger(__name__)


class LeadAnalyzer(Protocol):
    model_name: str

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        ...


class HeuristicLeadAnalyzer:
    model_name = "heuristic-v3"

    def __init__(self) -> None:
        self.calculator = BusinessCaseCalculator()

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        text = message_text.lower()
        intent = self._detect_intent(text)
        stage = self._detect_stage(intent, context.current_stage)
        action = self._detect_action(intent)
        selected_slot = self._detect_selected_slot(text)
        handoff_to_admin = self._needs_handoff(text)
        business_case = self.calculator.calculate(context.qualification_data)
        retrieved_knowledge = retrieve_company_knowledge(
            query=message_text,
            documents=context.company_knowledge,
            limit=3,
        )
        reply = self._build_reply(
            intent=intent,
            context=context,
            selected_slot=selected_slot,
            business_case=business_case.summary if business_case else "",
            retrieved_knowledge=retrieved_knowledge,
        )

        if selected_slot:
            stage = LeadStage.BOOKING_PENDING

        return AnalyzerResult(
            intent=intent,
            stage=stage,
            reply_text=reply,
            confidence=0.58,
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
        if any(x in text for x in ["созвон", "звонок", "консультац", "встреч", "бронь", "забронировать"]):
            return IntentType.BOOKING_INTENT
        if any(x in text for x in ["дорого", "не подходит", "сомневаюсь", "не уверен", "возраж"]):
            return IntentType.OBJECTION
        if any(x in text for x in ["привет", "здравствуйте", "добрый", "hello", "hi"]):
            return IntentType.GREETING
        if any(x in text for x in ["бот", "ассистент", "заявок", "поддержк", "услуг", "что уме", "что прода"]):
            return IntentType.SERVICE_QUESTION
        if any(x in text for x in ["@", "+7", "телефон", "почта", "email"]):
            return IntentType.CONTACT_SHARING
        return IntentType.UNCLEAR

    def _detect_stage(self, intent: IntentType, current_stage: LeadStage) -> LeadStage:
        mapping = {
            IntentType.GREETING: LeadStage.ENGAGED,
            IntentType.SERVICE_QUESTION: LeadStage.ENGAGED,
            IntentType.PRICE_QUESTION: LeadStage.INTERESTED,
            IntentType.OBJECTION: LeadStage.QUALIFIED,
            IntentType.READY_TO_BUY: LeadStage.BOOKING_PENDING,
            IntentType.BOOKING_INTENT: LeadStage.BOOKING_PENDING,
            IntentType.CONTACT_SHARING: LeadStage.QUALIFIED,
            IntentType.UNCLEAR: current_stage if current_stage != LeadStage.NEW else LeadStage.ENGAGED,
        }
        return mapping.get(intent, current_stage)

    def _detect_action(self, intent: IntentType) -> AssistantAction:
        if intent in {IntentType.BOOKING_INTENT, IntentType.READY_TO_BUY}:
            return AssistantAction.OFFER_CONSULTATION
        if intent in {IntentType.GREETING, IntentType.SERVICE_QUESTION, IntentType.UNCLEAR}:
            return AssistantAction.ASK_QUESTION
        if intent == IntentType.OBJECTION:
            return AssistantAction.REPLY
        return AssistantAction.REPLY

    def _needs_handoff(self, text: str) -> bool:
        return any(
            keyword in text
            for keyword in (
                "живой менеджер",
                "с менеджером",
                "оператор",
                "договор",
                "реквизиты",
                "коммерческое предложение",
            )
        )

    def _detect_selected_slot(self, text: str) -> str | None:
        parsed = parse_slot(text)
        if parsed is None:
            return None
        return parsed.strftime("%Y-%m-%d %H:%M")

    def _build_reply(
        self,
        *,
        intent: IntentType,
        context: AnalyzerContext,
        selected_slot: str | None,
        business_case: str,
        retrieved_knowledge: list[dict[str, str]],
    ) -> str:
        knowledge_text = self._knowledge_summary(retrieved_knowledge)
        known_phone = context.lead_profile.get("phone") or context.qualification_data.get("phone")

        if intent == IntentType.GREETING:
            return (
                "Привет. Я Алина, менеджер по продажам. "
                "Я могу рассказать, как AI-агент помогает компаниям быстрее отвечать клиентам, не терять заявки и доводить больше диалогов до денег. "
                "Для начала скажите, чем занимается ваш бизнес?"
            )

        if intent == IntentType.SERVICE_QUESTION:
            intro = knowledge_text or (
                "Мы внедряем AI-агента по продажам, который знает материалы компании, ведет клиентов по воронке и помогает доводить обращения до консультации или сделки."
            )
            return f"{intro} Чтобы понять, где это даст вам максимум пользы, расскажите, откуда к вам обычно приходят заявки?"

        if intent == IntentType.PRICE_QUESTION:
            return (
                "Стоимость внедрения составляет 200 000 рублей, а ежемесячное сопровождение — 20 000 рублей. "
                "Но здесь важнее не сама цена, а сколько денег вы теряете без быстрой и стабильной обработки заявок. "
                "Скажите, сколько обращений у вас примерно приходит в месяц?"
            )

        if intent == IntentType.OBJECTION:
            bridge = business_case or "Чаще всего компании теряют деньги именно на этапе ответа и доведения диалога до следующего шага."
            return (
                f"{bridge} Поэтому здесь важно смотреть не только на стоимость, а на то, сколько заявок и выручки можно вернуть. "
                "Если хотите, я коротко покажу, как это считается на вашем примере."
            )

        if intent in {IntentType.BOOKING_INTENT, IntentType.READY_TO_BUY}:
            if selected_slot and known_phone:
                return (
                    f"Хорошо. Зафиксировала консультацию на {selected_slot}. "
                    "Подтверждение отправлю на ваш номер, и если потребуется, отдельно напомню перед созвоном."
                )
            if selected_slot and not known_phone:
                return (
                    f"Время {selected_slot} подходит. Чтобы подтвердить консультацию, пришлите, пожалуйста, номер телефона, на который удобно отправить подтверждение."
                )
            return (
                "Хорошо, давайте перейдем к консультации. "
                "Напишите, пожалуйста, удобную дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ."
            )

        if intent == IntentType.CONTACT_SHARING:
            return (
                "Спасибо, контакт зафиксировала. "
                "Теперь давайте быстро пойму вашу текущую ситуацию: сколько заявок у вас примерно приходит в месяц?"
            )

        return (
            "Хочу лучше понять вашу ситуацию, чтобы не давать общие слова. "
            "Расскажите, пожалуйста, чем занимается ваш бизнес и где сейчас чаще всего теряются клиенты?"
        )

    def _knowledge_summary(self, retrieved_knowledge: list[dict[str, str]]) -> str:
        for item in retrieved_knowledge:
            text = " ".join(str(item.get("content") or "").split())
            if text:
                return text[:340].rstrip() + ("..." if len(text) > 340 else "")
        return ""


class OpenAILeadAnalyzer:
    def __init__(self) -> None:
        settings = get_settings()
        self.model_name = settings.openai_model
        self._temperature = settings.openai_temperature
        self._timeout = settings.openai_timeout_sec
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._calculator = BusinessCaseCalculator()

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        start = time.perf_counter()

        state_payload, state_usage = self._run_json_prompt(
            system_prompt=build_state_extractor_system_prompt(),
            user_prompt=build_state_extractor_user_prompt(
                message_text=message_text,
                current_stage=context.current_stage.value,
                history=context.history,
                lead_profile=context.lead_profile,
                qualification_data=context.qualification_data,
            ),
            temperature=0.0,
        )

        extracted_data = self._to_collected_data(state_payload.get("extracted_data"))
        merged_state = {**context.qualification_data, **extracted_data}
        retrieved_knowledge = retrieve_company_knowledge(
            query=" ".join(
                filter(
                    None,
                    [
                        message_text,
                        str(state_payload.get("summary") or ""),
                        str(merged_state.get("business_type") or ""),
                        str(merged_state.get("priority") or ""),
                    ],
                )
            ),
            documents=context.company_knowledge,
            limit=4,
        )
        business_case_result = self._calculator.calculate(merged_state)
        business_case = self._business_case_payload(business_case_result)

        strategy_payload, strategy_usage = self._run_json_prompt(
            system_prompt=build_strategy_system_prompt(),
            user_prompt=build_strategy_user_prompt(
                message_text=message_text,
                current_stage=context.current_stage.value,
                history=context.history,
                lead_profile=context.lead_profile,
                qualification_data=context.qualification_data,
                extracted_data=extracted_data,
                missing_data=self._to_string_list(state_payload.get("missing_data")),
                retrieved_knowledge=retrieved_knowledge,
                business_case=business_case,
            ),
            temperature=0.1,
        )

        response_payload, response_usage = self._run_json_prompt(
            system_prompt=build_response_writer_system_prompt(),
            user_prompt=build_response_writer_user_prompt(
                message_text=message_text,
                current_stage=context.current_stage.value,
                history=context.history,
                lead_profile=context.lead_profile,
                qualification_data=merged_state,
                retrieved_knowledge=retrieved_knowledge,
                business_case=business_case,
                strategy=strategy_payload,
            ),
            temperature=max(self._temperature, 0.3),
        )

        intent = self._to_intent(response_payload.get("intent") or state_payload.get("intent"))
        stage = self._to_stage(
            response_payload.get("stage") or strategy_payload.get("stage") or state_payload.get("stage"),
            fallback=context.current_stage,
        )
        reply_text = str(response_payload.get("reply_text") or "Уточните, пожалуйста, ваш запрос.").strip()
        confidence = max(
            self._to_confidence(state_payload.get("confidence")),
            self._to_confidence(strategy_payload.get("confidence")),
            self._to_confidence(response_payload.get("confidence")),
        )
        action = self._to_action(response_payload.get("action") or strategy_payload.get("action"))
        booking_candidate = response_payload.get("selected_slot") or state_payload.get("booking_time_candidate")
        selected_slot = self._to_selected_slot(booking_candidate)
        handoff_to_admin = bool(
            response_payload.get("handoff_to_admin")
            or strategy_payload.get("handoff_to_admin")
            or state_payload.get("should_handoff")
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        raw = {
            "provider": "openai-sales-runtime",
            "latency_ms": elapsed_ms,
            "state": state_payload,
            "strategy": strategy_payload,
            "response": response_payload,
            "business_case": business_case,
            "knowledge_titles": [item.get("title", "") for item in retrieved_knowledge],
            "usage": {
                "state": state_usage,
                "strategy": strategy_usage,
                "response": response_usage,
            },
        }

        logger.info(
            "AI analyzed message",
            extra={"intent": intent.value, "stage": stage.value, "latency_ms": elapsed_ms},
        )

        return AnalyzerResult(
            intent=intent,
            stage=stage,
            reply_text=reply_text,
            confidence=confidence,
            action=action,
            collected_data=extracted_data,
            selected_slot=selected_slot,
            handoff_to_admin=handoff_to_admin,
            raw=raw,
        )

    def _run_json_prompt(self, *, system_prompt: str, user_prompt: str, temperature: float) -> tuple[dict[str, Any], dict[str, Any] | None]:
        response = self._client.chat.completions.create(
            model=self.model_name,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=self._timeout,
        )
        content = response.choices[0].message.content or "{}"
        payload = self._safe_load_json(content)
        usage = response.usage.model_dump() if response.usage else None
        return payload, usage

    def _safe_load_json(self, content: str) -> dict[str, Any]:
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
            return 0.0
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

    def _to_string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _to_selected_slot(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        slot = value.strip()
        if not slot:
            return None
        parsed = parse_slot(slot)
        if parsed is None:
            return None
        return parsed.strftime("%Y-%m-%d %H:%M")

    def _business_case_payload(self, result: Any) -> dict[str, Any]:
        if result is None:
            return {}
        return {
            "monthly_leads": result.monthly_leads,
            "avg_ticket": result.avg_ticket,
            "conversion_rate": result.conversion_rate,
            "lost_leads_monthly": result.lost_leads_monthly,
            "recoverable_leads_monthly": result.recoverable_leads_monthly,
            "additional_revenue_monthly": result.additional_revenue_monthly,
            "payback_months": result.payback_months,
            "assumptions": result.assumptions,
            "summary": result.summary,
        }


def build_default_analyzer() -> LeadAnalyzer:
    settings = get_settings()
    if settings.openai_api_key:
        logger.info("Using OpenAI sales runtime", extra={"model": settings.openai_model})
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
