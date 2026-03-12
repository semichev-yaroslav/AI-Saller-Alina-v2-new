from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    price_from: Decimal | None = None
    currency: str | None = None
    is_active: bool
