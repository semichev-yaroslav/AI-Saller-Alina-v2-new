import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.analyzer import LeadAnalyzer
from app.api.deps import get_analyzer, get_db
from app.core.enums import MessageChannel
from app.schemas.simulate import SimulateMessageRequest, SimulateMessageResponse
from app.services.message_processor import IncomingMessageDTO, MessageProcessor

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/simulate/message", response_model=SimulateMessageResponse, tags=["simulation"])
def simulate_message(
    payload: SimulateMessageRequest,
    db: Session = Depends(get_db),
    analyzer: LeadAnalyzer = Depends(get_analyzer),
) -> SimulateMessageResponse:
    chat_id = payload.telegram_chat_id or payload.telegram_user_id

    processor = MessageProcessor(db, analyzer=analyzer)
    result = processor.process(
        IncomingMessageDTO(
            telegram_user_id=payload.telegram_user_id,
            telegram_chat_id=chat_id,
            username=payload.username,
            full_name=payload.full_name,
            text=payload.text,
            channel=MessageChannel.API_SIMULATION,
        )
    )

    logger.info("Simulation processed", extra={"lead_id": result.lead_id})

    return SimulateMessageResponse(
        lead_id=result.lead_id,
        incoming_message_id=result.incoming_message_id or "",
        outgoing_message_id=result.outgoing_message_id or "",
        intent=result.intent,
        stage=result.stage,
        confidence=result.confidence,
        reply_text=result.reply_text,
    )
