from datetime import UTC, datetime

from app.services.schedule import (
    MOSCOW_TZ,
    generate_consultation_slots,
    is_valid_consultation_slot,
    parse_slot,
    schedule_follow_up_at,
)


def test_follow_up_is_shifted_to_next_window_when_outside_hours() -> None:
    base_utc = datetime(2026, 3, 12, 18, 30, tzinfo=UTC)  # 21:30 МСК
    due_utc = schedule_follow_up_at(base_utc, 1)
    due_msk = due_utc.astimezone(MOSCOW_TZ)

    assert due_msk.hour == 11
    assert due_msk.minute == 0


def test_generated_slots_are_valid_consultation_windows() -> None:
    now_utc = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    slots = generate_consultation_slots(now_utc, days_ahead=1, limit=4)

    assert len(slots) == 4
    for raw_slot in slots:
        parsed = parse_slot(raw_slot)
        assert parsed is not None
        assert is_valid_consultation_slot(parsed, now_utc=now_utc)
