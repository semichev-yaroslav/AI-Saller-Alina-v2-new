from app.ai.analyzer import HeuristicLeadAnalyzer
from app.ai.contracts import AnalyzerContext
from app.core.enums import IntentType, LeadStage


def test_heuristic_detects_price_intent() -> None:
    analyzer = HeuristicLeadAnalyzer()
    context = AnalyzerContext(current_stage=LeadStage.NEW, history=[], services=[])

    result = analyzer.analyze("Сколько стоит AI-бот?", context)

    assert result.intent == IntentType.PRICE_QUESTION
    assert result.stage == LeadStage.INTERESTED
    assert 0.0 <= result.confidence <= 1.0


def test_heuristic_detects_booking() -> None:
    analyzer = HeuristicLeadAnalyzer()
    context = AnalyzerContext(current_stage=LeadStage.QUALIFIED, history=[], services=[])

    result = analyzer.analyze("Давайте созвон завтра в 14:00", context)

    assert result.intent == IntentType.BOOKING_INTENT
    assert result.stage == LeadStage.BOOKING_PENDING
