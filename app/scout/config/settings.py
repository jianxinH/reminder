from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.4", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    modelscope_api_key: str = Field(default="", alias="MODELSCOPE_API_KEY")
    modelscope_base_url: str = Field(default="", alias="MODELSCOPE_BASE_URL")
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
    newsletter_max_top_items: int = Field(default=3, alias="NEWSLETTER_MAX_TOP_ITEMS")
    newsletter_max_quick_hits: int = Field(default=8, alias="NEWSLETTER_MAX_QUICK_HITS")
    newsletter_max_related_links_per_item: int = Field(default=2, alias="NEWSLETTER_MAX_RELATED_LINKS_PER_ITEM")
    newsletter_max_items_per_source_in_top: int = Field(default=2, alias="NEWSLETTER_MAX_ITEMS_PER_SOURCE_IN_TOP")
    newsletter_max_items_per_topic_in_top: int = Field(default=1, alias="NEWSLETTER_MAX_ITEMS_PER_TOPIC_IN_TOP")
    newsletter_output_style: str = Field(default="feishu_compact", alias="NEWSLETTER_OUTPUT_STYLE")
    newsletter_summary_language: str = Field(default="zh", alias="NEWSLETTER_SUMMARY_LANGUAGE")
    newsletter_enable_trend_label: bool = Field(default=True, alias="NEWSLETTER_ENABLE_TREND_LABEL")
    newsletter_enable_editorial_reason: bool = Field(default=True, alias="NEWSLETTER_ENABLE_EDITORIAL_REASON")
    newsletter_filter_controversial_items: bool = Field(default=True, alias="NEWSLETTER_FILTER_CONTROVERSIAL_ITEMS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def llm_api_key(self) -> str:
        return (self.openai_api_key or self.modelscope_api_key).strip()

    @property
    def llm_base_url(self) -> str:
        if self.modelscope_api_key and self.modelscope_base_url:
            return self.modelscope_base_url.strip()
        if self.openai_api_key and self.openai_base_url:
            return self.openai_base_url.strip()
        if self.modelscope_base_url:
            return self.modelscope_base_url.strip()
        return (self.openai_base_url or "https://api.openai.com/v1").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
