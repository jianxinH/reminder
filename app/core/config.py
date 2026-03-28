from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Reminder Agent MVP"
    app_env: str = "dev"
    database_url: str = "sqlite:///./reminder.db"
    default_timezone: str = "Asia/Shanghai"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    modelscope_api_key: str = ""
    modelscope_model: str = "Qwen/Qwen2.5-72B-Instruct"
    modelscope_base_url: str = "https://api-inference.modelscope.cn/v1"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    wecom_corp_id: str = ""
    wecom_agent_id: str = ""
    wecom_secret: str = ""
    wecom_base_url: str = "https://qyapi.weixin.qq.com"
    wecom_token: str = ""
    wecom_aes_key: str = ""
    telegram_bot_token: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    scheduler_scan_interval_seconds: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
