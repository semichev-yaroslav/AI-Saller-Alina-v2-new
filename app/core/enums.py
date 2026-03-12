from enum import StrEnum


class IntentType(StrEnum):
    GREETING = "greeting"
    SERVICE_QUESTION = "service_question"
    PRICE_QUESTION = "price_question"
    OBJECTION = "objection"
    READY_TO_BUY = "ready_to_buy"
    BOOKING_INTENT = "booking_intent"
    CONTACT_SHARING = "contact_sharing"
    UNCLEAR = "unclear"


class LeadStage(StrEnum):
    NEW = "new"
    ENGAGED = "engaged"
    QUALIFIED = "qualified"
    INTERESTED = "interested"
    BOOKING_PENDING = "booking_pending"
    BOOKED = "booked"
    LOST = "lost"


class MessageSource(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageChannel(StrEnum):
    TELEGRAM = "telegram"
    API_SIMULATION = "api_simulation"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class AIRunStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
