from collections.abc import Generator
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.contracts import AnalyzerContext, AnalyzerResult
from app.api.deps import get_analyzer, get_db
from app.core.enums import IntentType, LeadStage
from app.db.base import Base
from app.db.models import ai_run, lead, message, service  # noqa: F401
from app.main import app


class FakeAnalyzer:
    model_name = "fake-analyzer"

    def analyze(self, message_text: str, context: AnalyzerContext) -> AnalyzerResult:
        text = message_text.lower()
        if "цена" in text or "стоит" in text:
            intent = IntentType.PRICE_QUESTION
            stage = LeadStage.INTERESTED
            reply = "Базовые цены указаны в каталоге. Опишите объем задачи, и я уточню оценку."
            confidence = 0.9
        elif "куп" in text:
            intent = IntentType.READY_TO_BUY
            stage = LeadStage.BOOKING_PENDING
            reply = "Отлично, готов оформить следующий шаг. Оставьте контакт и удобное время."
            confidence = 0.88
        else:
            intent = IntentType.SERVICE_QUESTION
            stage = LeadStage.QUALIFIED
            reply = "Уточните, какую задачу нужно автоматизировать в первую очередь."
            confidence = 0.8

        return AnalyzerResult(
            intent=intent,
            stage=stage,
            reply_text=reply,
            confidence=confidence,
            raw={"provider": "fake"},
        )


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_analyzer] = lambda: FakeAnalyzer()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
