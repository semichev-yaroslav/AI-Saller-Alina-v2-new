from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import DeliveryStatus, MessageChannel, MessageSource


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    lead_id: str
    source: MessageSource
    channel: MessageChannel
    text: str
    telegram_message_id: int | None = None
    telegram_update_id: int | None = None
    delivery_status: DeliveryStatus
    delivery_error: str | None = None
    created_at: datetime
