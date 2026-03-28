import httpx

from app.core.config import get_settings


class TelegramService:
    def __init__(self):
        self.settings = get_settings()

    async def send_message(self, chat_id: str, text: str) -> dict:
        if not self.settings.telegram_bot_token:
            return {"ok": False, "description": "Telegram bot token is not configured"}

        url = f"{self.settings.telegram_api_base}/bot{self.settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
            response.raise_for_status()
            return response.json()
