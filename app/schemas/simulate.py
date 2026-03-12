from pydantic import BaseModel, Field

from app.core.enums import IntentType, LeadStage


class SimulateMessageRequest(BaseModel):
    telegram_user_id: int = Field(..., gt=0)
    telegram_chat_id: int | None = Field(default=None, gt=0)
    username: str | None = None
    full_name: str | None = None
    text: str = Field(..., min_length=1)


class SimulateMessageResponse(BaseModel):
    lead_id: str
    incoming_message_id: str
    outgoing_message_id: str
    intent: IntentType
    stage: LeadStage
    confidence: float
    reply_text: str
