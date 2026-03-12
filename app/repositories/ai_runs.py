from sqlalchemy.orm import Session

from app.core.enums import AIRunStatus, IntentType, LeadStage
from app.db.models.ai_run import AIRun


class AIRunRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        lead_id: str,
        input_message_id: str,
        model: str,
        prompt_version: str,
        intent: IntentType | None,
        predicted_stage: LeadStage | None,
        confidence: float | None,
        reply_text: str | None,
        raw_response: dict | None,
        latency_ms: int | None,
        status: AIRunStatus,
        error_text: str | None = None,
    ) -> AIRun:
        run = AIRun(
            lead_id=lead_id,
            input_message_id=input_message_id,
            model=model,
            prompt_version=prompt_version,
            intent=intent,
            predicted_stage=predicted_stage,
            confidence=confidence,
            reply_text=reply_text,
            raw_response=raw_response,
            latency_ms=latency_ms,
            status=status,
            error_text=error_text,
        )
        self.db.add(run)
        self.db.flush()
        return run
