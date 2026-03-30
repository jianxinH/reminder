from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.scout.config.settings import get_settings
from app.scout.delivery.markdown_writer import write_markdown_report
from app.scout.fetchers.rss_fetcher import fetch_all_rss_items
from app.scout.pipeline.classify import classify_items
from app.scout.pipeline.dedupe import dedupe_items
from app.scout.pipeline.normalize import normalize_items
from app.scout.pipeline.report_builder import build_daily_report
from app.scout.pipeline.summarize import NewsSummarizer
from app.scout.storage.db import init_db
from app.scout.storage.repository import ArticleRepository
from app.scout.utils.logger import get_logger

logger = get_logger(__name__)


def ensure_directories() -> None:
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("reports").mkdir(parents=True, exist_ok=True)


def filter_recent_items(
    items: list[dict[str, Any]],
    recent_days: int,
    timezone_name: str,
) -> list[dict[str, Any]]:
    if recent_days <= 0:
        return items

    tz = ZoneInfo(timezone_name)
    cutoff = datetime.now(tz) - timedelta(days=recent_days)
    filtered: list[dict[str, Any]] = []

    for item in items:
        published_at = parse_datetime(item.get("published_at", ""), tz)
        if published_at is None:
            continue
        if published_at >= cutoff:
            filtered.append(item)

    return filtered


def parse_datetime(value: str, timezone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def sort_items_by_published_at(
    items: list[dict[str, Any]],
    timezone_name: str,
) -> list[dict[str, Any]]:
    tz = ZoneInfo(timezone_name)
    return sorted(
        items,
        key=lambda item: parse_datetime(item.get("published_at", ""), tz) or datetime.min.replace(tzinfo=tz),
        reverse=True,
    )


def run_pipeline() -> dict[str, Any]:
    settings = get_settings()
    ensure_directories()
    init_db(settings.database_path)

    repository = ArticleRepository(settings.database_path)
    summarizer = NewsSummarizer(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        language=settings.report_language,
    )

    logger.info("开始抓取 RSS 资讯...")
    raw_items = fetch_all_rss_items(settings.sources_file)
    logger.info("原始抓取条数: %s", len(raw_items))

    normalized_items = normalize_items(raw_items)
    logger.info("标准化后条数: %s", len(normalized_items))

    recent_items = filter_recent_items(
        normalized_items,
        recent_days=settings.recent_days,
        timezone_name=settings.report_timezone,
    )
    logger.info("最近 %s 天内条数: %s", settings.recent_days, len(recent_items))

    filtered_items: list[dict[str, Any]] = []
    for item in recent_items:
        if repository.exists_by_url(item["url"]):
            continue
        filtered_items.append(item)

    logger.info("过滤数据库中已存在 URL 后条数: %s", len(filtered_items))

    unique_items = dedupe_items(filtered_items)
    logger.info("去重后条数: %s", len(unique_items))

    classified_items = classify_items(sort_items_by_published_at(unique_items, settings.report_timezone))

    summarized_items: list[dict[str, Any]] = []
    inserted_count = 0
    summarized_count = 0
    summary_limit = max(0, settings.max_summary_items)

    for index, item in enumerate(classified_items, start=1):
        article_id = repository.insert_article(item)
        inserted_count += 1

        should_summarize = index <= summary_limit
        if should_summarize:
            logger.info("正在摘要第 %s/%s 条: %s", index, len(classified_items), item.get("title", ""))
            summary_result = summarizer.summarize_item(item)
            summarized_count += 1
        else:
            summary_result = summarizer.fallback_summary(item, reason="超过本次摘要上限，已使用原始摘要。")

        repository.insert_article_summary(article_id, summary_result)
        summarized_items.append({**item, **summary_result})

    included_items = [item for item in summarized_items if item.get("include_in_report", True)]

    report_markdown = build_daily_report(
        items=included_items,
        top_n=settings.report_top_n,
        timezone_name=settings.report_timezone,
    )

    report_path = write_markdown_report(
        content=report_markdown,
        output_dir="reports",
        timezone_name=settings.report_timezone,
    )
    repository.insert_report(report_path=report_path, item_count=len(included_items))

    stats = {
        "fetched_count": len(raw_items),
        "normalized_count": len(normalized_items),
        "recent_count": len(recent_items),
        "deduped_count": len(unique_items),
        "inserted_count": inserted_count,
        "summarized_count": summarized_count,
        "included_count": len(included_items),
        "report_path": str(report_path),
    }
    logger.info("处理完成: %s", stats)
    return stats


def main() -> None:
    try:
        stats = run_pipeline()
        print("\n=== AI Daily Scout ===")
        print(f"抓取条数: {stats['fetched_count']}")
        print(f"标准化后条数: {stats['normalized_count']}")
        print(f"最近时间窗条数: {stats['recent_count']}")
        print(f"去重后条数: {stats['deduped_count']}")
        print(f"写入数据库条数: {stats['inserted_count']}")
        print(f"调用摘要条数: {stats['summarized_count']}")
        print(f"收录到日报条数: {stats['included_count']}")
        print(f"日报输出路径: {stats['report_path']}")
    except Exception as exc:
        logger.exception("主流程运行失败: %s", exc)
        raise


if __name__ == "__main__":
    main()
