#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.models.lead import Lead
from app.db.session import SessionLocal
from app.services.message_processor import IncomingMessageDTO, MessageProcessor
from app.core.enums import MessageChannel


@dataclass(slots=True)
class DialogCase:
    name: str
    messages: list[str]


DEFAULT_CASES: list[DialogCase] = [
    DialogCase(
        name="hot_lead_to_booking",
        messages=[
            "/start",
            "Мы строим дома под ключ, заявки из Telegram и Instagram",
            "Около 60 заявок в месяц, средний чек 2 млн",
            "Отвечаем обычно через 2-3 часа, часть диалогов теряется",
            "Для нас главное не терять заявки",
            "Давайте консультацию завтра в 11",
        ],
    ),
    DialogCase(
        name="price_objection_then_booking",
        messages=[
            "/start",
            "Сколько стоит внедрение?",
            "Дорого, почему такая цена?",
            "Покажите как это окупается на практике",
            "Ок, давайте консультацию завтра в 15:00",
        ],
    ),
    DialogCase(
        name="stop_and_reactivate",
        messages=[
            "/start",
            "Стоп, не пишите",
            "Снова актуально, давайте продолжим",
            "У нас клиника, около 40 заявок в месяц",
            "Давайте консультацию завтра в 11:30",
        ],
    ),
    DialogCase(
        name="handoff_request",
        messages=[
            "/start",
            "Нужны реквизиты и договор, подключите живого менеджера",
            "Ок, спасибо",
        ],
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate multiple sales dialogs locally.")
    parser.add_argument(
        "--base-user-id",
        type=int,
        default=None,
        help="Base telegram_user_id for generated dialogs. Defaults to timestamp-based value.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = datetime.now(UTC)
    base_user_id = args.base_user_id or (800_000_000 + (int(now.timestamp()) % 100_000))

    print(f"Starting dialog simulation. base_user_id={base_user_id}")
    print("Cases:", ", ".join(case.name for case in DEFAULT_CASES))
    print()

    db = SessionLocal()
    try:
        processor = MessageProcessor(db)

        for offset, case in enumerate(DEFAULT_CASES):
            user_id = base_user_id + offset
            chat_id = user_id

            print("=" * 88)
            print(f"[CASE] {case.name} | telegram_user_id={user_id}")
            print("-" * 88)

            for index, text in enumerate(case.messages, start=1):
                print(f"[USER #{index}] {text}")
                result = processor.process(
                    IncomingMessageDTO(
                        telegram_user_id=user_id,
                        telegram_chat_id=chat_id,
                        username=f"sim_{case.name}",
                        full_name=f"Sim {case.name}",
                        text=text,
                        channel=MessageChannel.API_SIMULATION,
                    )
                )
                reply = result.reply_text.replace("\n", " ")
                if len(reply) > 220:
                    reply = reply[:217] + "..."
                print(f"[BOT ] {reply}")
                print(f"       intent={result.intent.value} stage={result.stage.value} conf={result.confidence:.2f}")

            lead = db.scalar(select(Lead).where(Lead.telegram_user_id == user_id))
            if lead is not None:
                print("-" * 88)
                print(
                    "FINAL:"
                    f" stage={lead.stage.value}"
                    f", do_not_contact={lead.do_not_contact}"
                    f", booking_slot_at={lead.booking_slot_at}"
                    f", handoff_requested={lead.handoff_requested}"
                    f", next_follow_up_at={lead.next_follow_up_at}"
                )
            print()

        print("=" * 88)
        print("[SUMMARY] Lead stages in database:")
        stage_counts = db.connection().exec_driver_sql(
            "SELECT UPPER(stage) as stage, COUNT(*) as cnt FROM leads GROUP BY UPPER(stage) ORDER BY cnt DESC"
        ).fetchall()
        for stage, count in stage_counts:
            print(f"- {stage}: {count}")

    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
