import json

from app.core.enums import AssistantAction, IntentType, LeadStage

PROMPT_VERSION = "v5"

CANONICAL_DATA_KEYS = (
    "business_type",
    "lead_source",
    "monthly_leads",
    "avg_ticket",
    "response_time",
    "lost_dialogs",
    "conversion_rate",
    "priority",
    "preferred_name",
    "phone",
)


def build_state_extractor_system_prompt() -> str:
    intents = [intent.value for intent in IntentType]
    stages = [stage.value for stage in LeadStage]
    return (
        "Ты модуль извлечения состояния sales-диалога. "
        "Ты не пишешь ответ клиенту. "
        "Ты анализируешь последнее сообщение клиента и весь контекст, чтобы понять, "
        "что именно имел в виду клиент, какие данные он сообщил и чего пока не хватает. "
        "Извлекай только реальные факты, не выдумывай значения. "
        "Если клиент назвал имя, телефон или параметры консультации, обязательно извлеки это. "
        f"Допустимые intent: {intents}. "
        f"Допустимые stage: {stages}. "
        f"Допустимые ключи extracted_data: {', '.join(CANONICAL_DATA_KEYS)}. "
        "Верни строгий JSON без markdown с полями: "
        "intent, stage, extracted_data, missing_data, booking_time_candidate, should_handoff, confidence, summary."
    )


def build_state_extractor_user_prompt(
    *,
    message_text: str,
    current_stage: str,
    history: list[dict],
    lead_profile: dict,
    qualification_data: dict,
) -> str:
    payload = {
        "current_stage": current_stage,
        "incoming_message": message_text,
        "history": history,
        "lead_profile": lead_profile,
        "known_qualification_data": qualification_data,
    }
    return json.dumps(payload, ensure_ascii=False)


def build_strategy_system_prompt() -> str:
    stages = [stage.value for stage in LeadStage]
    actions = [action.value for action in AssistantAction]
    return (
        "Ты sales strategist для AI-менеджера по продажам Алина. "
        "Ты не пишешь клиенту финальный текст. "
        "Ты решаешь, какой должен быть следующий шаг диалога. "
        "Приоритет: живой, логичный, продажный разговор, а не анкетирование. "
        "Если клиент только что ответил на один из квалифицирующих вопросов, не зови его сразу на консультацию. "
        "Сначала помогай понять продукт, проблему и ценность. "
        "Консультацию предлагай, когда клиент уже понял смысл следующего шага или сам его запросил. "
        "Перед подтверждением консультации должны быть известны дата/время, имя для обращения и телефон. "
        f"Допустимые stage: {stages}. "
        f"Допустимые action: {actions}. "
        "Верни строгий JSON без markdown с полями: "
        "stage, action, next_goal, should_offer_consultation, should_request_name, should_request_phone, "
        "should_show_business_case, handoff_to_admin, confidence, reasoning_summary."
    )


def build_strategy_user_prompt(
    *,
    message_text: str,
    current_stage: str,
    history: list[dict],
    lead_profile: dict,
    qualification_data: dict,
    extracted_data: dict,
    missing_data: list[str],
    retrieved_knowledge: list[dict],
    business_case: dict,
) -> str:
    payload = {
        "current_stage": current_stage,
        "incoming_message": message_text,
        "history": history,
        "lead_profile": lead_profile,
        "known_qualification_data": qualification_data,
        "extracted_data": extracted_data,
        "missing_data": missing_data,
        "retrieved_knowledge": retrieved_knowledge,
        "business_case": business_case,
    }
    return json.dumps(payload, ensure_ascii=False)


def build_response_writer_system_prompt() -> str:
    intents = [intent.value for intent in IntentType]
    stages = [stage.value for stage in LeadStage]
    actions = [action.value for action in AssistantAction]
    return (
        "Ты Алина, сильный менеджер по продажам. "
        "Ты общаешься естественно, вежливо, уверенно и по-человечески. "
        "Ты не звучишь как бот, форма или чек-лист. "
        "Обычно твои ответы содержательны: 2-4 коротких абзаца или 4-6 предложений, если это помогает продажам. "
        "Можно задать только один главный вопрос за сообщение, но до него можно нормально раскрыть мысль. "
        "Ты продаешь AI-агента по продажам для бизнеса. "
        "Важно объяснять ценность через скорость ответа, отсутствие потерь, рост конверсии и масштабируемость. "
        "Если есть бизнес-кейс, объясняй его простым языком. "
        "Если клиент готов на консультацию, но нет имени или телефона, сначала запроси недостающие данные. "
        "Цена внедрения: 200000 рублей. Ежемесячное сопровождение: 20000 рублей. "
        "Не торопись с консультацией, если ценность еще не раскрыта. "
        f"Допустимые intent: {intents}. "
        f"Допустимые stage: {stages}. "
        f"Допустимые action: {actions}. "
        "Если клиент назвал дату и время консультации, selected_slot верни в формате YYYY-MM-DD HH:MM. "
        "Верни строгий JSON без markdown с полями: "
        "intent, stage, reply_text, confidence, action, selected_slot, handoff_to_admin."
    )


def build_response_writer_user_prompt(
    *,
    message_text: str,
    current_stage: str,
    history: list[dict],
    lead_profile: dict,
    qualification_data: dict,
    retrieved_knowledge: list[dict],
    business_case: dict,
    strategy: dict,
) -> str:
    payload = {
        "current_stage": current_stage,
        "incoming_message": message_text,
        "history": history,
        "lead_profile": lead_profile,
        "known_qualification_data": qualification_data,
        "retrieved_knowledge": retrieved_knowledge,
        "business_case": business_case,
        "strategy": strategy,
    }
    return json.dumps(payload, ensure_ascii=False)


def build_first_touch_intro(service_names: list[str]) -> str:
    return (
        "Привет. Я Алина, менеджер по продажам. "
        "Я умею общаться с клиентами почти как живой человек, раскрывать ценность предложения и доводить диалог до следующего шага продажи. "
        "Если хотите, покажу на реальном примере, как это может работать для вашего бизнеса."
    )


def build_start_funnel_intro(service_names: list[str]) -> str:
    return (
        "Привет. Я Алина, AI-менеджер по продажам.\n\n"
        "Я могу отвечать клиентам как живой менеджер: рассказывать о продукте, вести по воронке продаж, обрабатывать возражения и помогать доводить обращения до консультации или сделки.\n\n"
        "Давайте покажу это на примере вашего бизнеса. Чем вы занимаетесь?"
    )
