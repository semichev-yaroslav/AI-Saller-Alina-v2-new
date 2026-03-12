from pydantic import BaseModel, Field

from app.core.enums import AssistantAction, IntentType, LeadStage


class AnalyzerContext(BaseModel):
    current_stage: LeadStage
    history: list[dict[str, str]]
    services: list[dict[str, str]]
    qualification_data: dict[str, str | int | float] = Field(default_factory=dict)
    available_slots: list[str] = Field(default_factory=list)


class AnalyzerResult(BaseModel):
    intent: IntentType
    stage: LeadStage
    reply_text: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    action: AssistantAction = AssistantAction.REPLY
    collected_data: dict[str, str | int | float] = Field(default_factory=dict)
    selected_slot: str | None = None
    handoff_to_admin: bool = False
    raw: dict = Field(default_factory=dict)
