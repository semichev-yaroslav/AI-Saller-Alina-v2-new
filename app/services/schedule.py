from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

FOLLOW_UP_WINDOW_START_HOUR = 11
FOLLOW_UP_WINDOW_END_HOUR = 20
FOLLOW_UP_DELAYS_HOURS = {1: 2, 2: 24, 3: 72}

CONSULTATION_WINDOW_START_HOUR = 11
CONSULTATION_WINDOW_END_HOUR = 17
CONSULTATION_SLOT_MINUTES = 30

FOLLOW_UP_TEMPLATES = {
    1: "Возможно, вы пропустили сообщение. Хотите посмотреть пример, как работает автоматический менеджер?",
    2: "Могу показать, как такой бот работает на вашем бизнесе. Есть несколько свободных окон для консультации.",
    3: "Отправлю короткий чек-лист: как бизнес теряет заявки в мессенджерах.",
}


def schedule_follow_up_at(base_utc: datetime, step: int) -> datetime:
    delay_hours = FOLLOW_UP_DELAYS_HOURS.get(step)
    if delay_hours is None:
        raise ValueError(f"Unsupported follow-up step: {step}")

    due_msk = base_utc.astimezone(MOSCOW_TZ) + timedelta(hours=delay_hours)
    due_msk = _shift_to_follow_up_window(due_msk)
    return due_msk.astimezone(UTC)


def follow_up_message(step: int) -> str:
    return FOLLOW_UP_TEMPLATES[step]


def generate_consultation_slots(now_utc: datetime, *, days_ahead: int = 3, limit: int = 8) -> list[str]:
    now_msk = now_utc.astimezone(MOSCOW_TZ)
    slots: list[str] = []

    for day_offset in range(days_ahead + 1):
        day = (now_msk + timedelta(days=day_offset)).date()
        hour = CONSULTATION_WINDOW_START_HOUR
        minute = 0
        while hour < CONSULTATION_WINDOW_END_HOUR:
            slot_msk = datetime.combine(day, time(hour=hour, minute=minute), tzinfo=MOSCOW_TZ)
            if slot_msk > now_msk:
                slots.append(slot_msk.strftime("%Y-%m-%d %H:%M"))
                if len(slots) >= limit:
                    return slots

            minute += CONSULTATION_SLOT_MINUTES
            if minute >= 60:
                hour += 1
                minute = 0

    return slots


def parse_slot(slot_value: str) -> datetime | None:
    value = slot_value.strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=MOSCOW_TZ)
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=MOSCOW_TZ)
    return parsed.astimezone(MOSCOW_TZ)


def is_valid_consultation_slot(slot_msk: datetime, *, now_utc: datetime) -> bool:
    localized = slot_msk.astimezone(MOSCOW_TZ)
    now_msk = now_utc.astimezone(MOSCOW_TZ)

    if localized <= now_msk:
        return False
    if localized.minute not in {0, 30}:
        return False
    if localized.second != 0 or localized.microsecond != 0:
        return False
    return CONSULTATION_WINDOW_START_HOUR <= localized.hour < CONSULTATION_WINDOW_END_HOUR


def _shift_to_follow_up_window(moment_msk: datetime) -> datetime:
    if moment_msk.hour < FOLLOW_UP_WINDOW_START_HOUR:
        return moment_msk.replace(hour=FOLLOW_UP_WINDOW_START_HOUR, minute=0, second=0, microsecond=0)

    if moment_msk.hour >= FOLLOW_UP_WINDOW_END_HOUR:
        next_day = moment_msk + timedelta(days=1)
        return next_day.replace(hour=FOLLOW_UP_WINDOW_START_HOUR, minute=0, second=0, microsecond=0)

    return moment_msk
