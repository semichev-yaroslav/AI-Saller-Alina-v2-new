import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TelegramInboundMessage:
    update_id: int
    message_id: int
    user_id: int
    chat_id: int
    username: str | None
    full_name: str | None
    text: str


class TelegramBotClient:
    def __init__(self, token: str, timeout_sec: float = 30.0) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout_sec = timeout_sec
        self._client = httpx.Client(timeout=timeout_sec)

    def get_updates(self, *, offset: int | None = None, timeout: int = 25) -> list[TelegramInboundMessage]:
        payload: dict[str, int] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset

        response = self._client.get(f"{self.base_url}/getUpdates", params=payload)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {data}")

        updates: list[TelegramInboundMessage] = []
        for item in data.get("result", []):
            message = item.get("message")
            if not message:
                continue

            text = message.get("text")
            if not text:
                continue

            sender = message.get("from") or {}
            chat = message.get("chat") or {}

            full_name = " ".join(part for part in [sender.get("first_name"), sender.get("last_name")] if part).strip()

            updates.append(
                TelegramInboundMessage(
                    update_id=item["update_id"],
                    message_id=message["message_id"],
                    user_id=sender["id"],
                    chat_id=chat["id"],
                    username=sender.get("username"),
                    full_name=full_name or None,
                    text=text,
                )
            )
        return updates

    def send_message(self, chat_id: int, text: str) -> int | None:
        response = self._client.post(f"{self.base_url}/sendMessage", json={"chat_id": chat_id, "text": text})
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data}")

        result = data.get("result") or {}
        return result.get("message_id")
