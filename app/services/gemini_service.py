from functools import cached_property

from google import genai

from app.core.config import get_settings


class GeminiService:
    def __init__(self):
        self.settings = get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.gemini_api_key)

    @cached_property
    def client(self) -> genai.Client:
        return genai.Client(api_key=self.settings.gemini_api_key)
