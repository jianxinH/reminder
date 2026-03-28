import httpx

from app.core.config import get_settings


class ModelScopeService:
    def __init__(self):
        self.settings = get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.modelscope_api_key and self.settings.modelscope_model)

    async def create_chat_completion(self, messages: list[dict], tools: list[dict] | None = None, tool_choice: str = "auto") -> dict:
        base_url = self.settings.modelscope_base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        payload: dict = {
            "model": self.settings.modelscope_model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.settings.modelscope_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            return response.json()
