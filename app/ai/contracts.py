from pydantic import BaseModel, Field

from app.core.enums import IntentType, LeadStage


class AnalyzerContext(BaseModel):
    current_stage: LeadStage
    history: list[dict[str, str]]
    services: list[dict[str, str]]


class AnalyzerResult(BaseModel):
    intent: IntentType
    stage: LeadStage
    reply_text: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    raw: dict = Field(default_factory=dict)
