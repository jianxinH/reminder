from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.4", alias="OPENAI_MODEL")
    database_path: str = Field(default="data/scout.db", alias="SCOUT_DATABASE_PATH")
    sources_file: str = Field(
        default=str(BASE_DIR / "app" / "scout" / "config" / "sources.yaml"),
        alias="SCOUT_SOURCES_FILE",
    )
    report_timezone: str = Field(default="Asia/Shanghai", alias="REPORT_TIMEZONE")
    report_language: str = Field(default="zh-CN", alias="REPORT_LANGUAGE")
    report_top_n: int = Field(default=20, alias="REPORT_TOP_N")
    recent_days: int = Field(default=3, alias="SCOUT_RECENT_DAYS")
    max_summary_items: int = Field(default=30, alias="SCOUT_MAX_SUMMARY_ITEMS")
    log_level: str = Field(default="INFO", alias="SCOUT_LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
