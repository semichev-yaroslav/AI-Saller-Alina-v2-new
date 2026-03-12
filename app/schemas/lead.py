from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

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
    qualification_data: dict = Field(default_factory=dict)
    follow_up_step: int = 0
    next_follow_up_at: datetime | None = None
    do_not_contact: bool = False
    stopped_at: datetime | None = None
    last_user_message_at: datetime | None = None
    last_bot_message_at: datetime | None = None
    booking_slot_at: datetime | None = None
    handoff_requested: bool = False


class LeadRead(LeadBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
