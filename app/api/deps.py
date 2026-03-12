from functools import lru_cache

from sqlalchemy.orm import Session

from app.ai.analyzer import LeadAnalyzer, build_default_analyzer
from app.db.session import get_db
from app.services.message_processor import MessageProcessor


@lru_cache
def get_analyzer() -> LeadAnalyzer:
    return build_default_analyzer()


def get_message_processor(db: Session) -> MessageProcessor:
    return MessageProcessor(db, analyzer=get_analyzer())


__all__ = ["get_db", "get_message_processor", "get_analyzer"]
