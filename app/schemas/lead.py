from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import IntentType, LeadStage


class LeadBase(BaseModel):
    telegram_user_id: int
    telegram_chat_id: int
    username: str | None = None
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    stage: LeadStage
    last_intent: IntentType | None = None


class LeadRead(LeadBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
