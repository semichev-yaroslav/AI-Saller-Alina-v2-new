import logging
import time

from app.core.config import get_settings
from app.core.enums import MessageChannel
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.integrations.telegram_bot import TelegramBotClient
from app.services.message_processor import IncomingMessageDTO, MessageProcessor

logger = logging.getLogger(__name__)


def run_polling() -> None:
    configure_logging()
    settings = get_settings()

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required to run telegram polling worker")

    bot = TelegramBotClient(token=settings.telegram_bot_token, timeout_sec=settings.telegram_poll_timeout_sec + 10)
    offset: int | None = None

    logger.info("Telegram polling worker started")

    while True:
        try:
            updates = bot.get_updates(offset=offset, timeout=settings.telegram_poll_timeout_sec)
            if updates:
                logger.info("Received telegram updates", extra={"count": len(updates)})

            for upd in updates:
                offset = upd.update_id + 1
                db = SessionLocal()
                try:
                    processor = MessageProcessor(db, telegram_sender=bot)
                    result = processor.process(
                        IncomingMessageDTO(
                            telegram_user_id=upd.user_id,
                            telegram_chat_id=upd.chat_id,
                            username=upd.username,
                            full_name=upd.full_name,
                            text=upd.text,
                            channel=MessageChannel.TELEGRAM,
                            telegram_message_id=upd.message_id,
                            telegram_update_id=upd.update_id,
                        )
                    )
                    if result.duplicate:
                        logger.info("Skipped duplicate telegram update", extra={"update_id": upd.update_id})
                finally:
                    db.close()

            if not updates:
                time.sleep(settings.telegram_poll_interval_sec)

        except Exception:  # noqa: BLE001
            logger.exception("Polling loop error")
            time.sleep(max(settings.telegram_poll_interval_sec, 2.0))


if __name__ == "__main__":
    run_polling()
