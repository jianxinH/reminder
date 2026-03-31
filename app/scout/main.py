from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.scout.config.settings import get_settings
from app.scout.delivery.markdown_writer import write_markdown_report
from app.scout.fetchers.rss_fetcher import fetch_all_rss_items
from app.scout.pipeline.classify import classify_items
from app.scout.pipeline.daily_editor import DailyEditor
from app.scout.pipeline.dedupe import dedupe_items
from app.scout.pipeline.normalize import normalize_items
from app.scout.pipeline.report_builder import build_daily_report
from app.scout.pipeline.summarize import NewsSummarizer
from app.scout.storage.db import init_db
from app.scout.storage.repository import ArticleRepository
from app.scout.utils.logger import get_logger

logger = get_logger(__name__)

TOP_THRESHOLD = 75
REGULAR_THRESHOLD = 60
MIN_REPORT_ITEMS = 12
TARGET_REPORT_ITEMS = 18
MIN_LOW_PRIORITY_ITEMS = 6


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
            filtered.append(item)
            continue
        if published_at >= cutoff:
            filtered.append(item)
    return filtered


def parse_datetime(value: str, timezone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def sort_items_by_priority(items: list[dict[str, Any]], timezone_name: str) -> list[dict[str, Any]]:
    tz = ZoneInfo(timezone_name)
    return sorted(
        items,
        key=lambda item: (
            int(item.get("importance_score", 0)),
            int(item.get("priority", 50)),
            parse_datetime(item.get("published_at", ""), tz) or datetime.min.replace(tzinfo=tz),
        ),
        reverse=True,
    )


def partition_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    sorted_items = sorted(
        items,
        key=lambda item: (int(item.get("importance_score", 0)), int(item.get("priority", 50))),
        reverse=True,
    )

    top_candidates = [item for item in sorted_items if item.get("importance_score", 0) >= TOP_THRESHOLD]
    regular_candidates = [
        item
        for item in sorted_items
        if item not in top_candidates
        and item.get("is_ai_related", True)
        and item.get("importance_score", 0) >= REGULAR_THRESHOLD
    ]
    low_priority_candidates = [
        item
        for item in sorted_items
        if item not in top_candidates and item not in regular_candidates and item.get("is_ai_related", True)
    ]

    if len(top_candidates) < 3:
        needed = 3 - len(top_candidates)
        top_candidates.extend(regular_candidates[:needed])
        regular_candidates = regular_candidates[needed:]

    regular_candidates, low_priority_candidates = ensure_category_presence(
        regular_candidates,
        low_priority_candidates,
        preferred_categories={"研究", "新闻", "其他"},
        minimum_per_category=1,
    )

    included_count = len(top_candidates) + len(regular_candidates)
    if included_count < TARGET_REPORT_ITEMS:
        promote_count = min(TARGET_REPORT_ITEMS - included_count, len(low_priority_candidates))
        regular_candidates.extend(low_priority_candidates[:promote_count])
        low_priority_candidates = low_priority_candidates[promote_count:]

    if len(low_priority_candidates) < MIN_LOW_PRIORITY_ITEMS:
        spillback_count = min(
            MIN_LOW_PRIORITY_ITEMS - len(low_priority_candidates),
            max(len(regular_candidates) - MIN_REPORT_ITEMS, 0),
        )
        if spillback_count > 0:
            spillback_items = regular_candidates[-spillback_count:]
            regular_candidates = regular_candidates[:-spillback_count]
            low_priority_candidates = spillback_items + low_priority_candidates

    section_items: dict[str, list[dict[str, Any]]] = {}
    for item in regular_candidates:
        category = item.get("category_suggestion") or item.get("category") or "其他"
        section_items.setdefault(category, []).append(item)

    return top_candidates[:3], section_items, low_priority_candidates


def ensure_category_presence(
    regular_candidates: list[dict[str, Any]],
    low_priority_candidates: list[dict[str, Any]],
    *,
    preferred_categories: set[str],
    minimum_per_category: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    regular = list(regular_candidates)
    low_priority = list(low_priority_candidates)

    for category in preferred_categories:
        current_count = sum(
            1
            for item in regular
            if (item.get("category_suggestion") or item.get("category") or "其他") == category
        )
        if current_count >= minimum_per_category:
            continue

        needed = minimum_per_category - current_count
        matching = [
            item
            for item in low_priority
            if (item.get("category_suggestion") or item.get("category") or "其他") == category
        ][:needed]
        if not matching:
            continue

        regular.extend(matching)
        low_priority = [item for item in low_priority if item not in matching]

    regular.sort(key=lambda item: (int(item.get("importance_score", 0)), int(item.get("priority", 50))), reverse=True)
    low_priority.sort(key=lambda item: (int(item.get("importance_score", 0)), int(item.get("priority", 50))), reverse=True)
    return regular, low_priority


def supplement_with_recent_database_items(
    repository: ArticleRepository,
    eligible_items: list[dict[str, Any]],
    recent_days: int,
    report_top_n: int,
) -> tuple[list[dict[str, Any]], int]:
    stored_items = repository.get_recent_report_items(
        recent_days=recent_days,
        limit=max(report_top_n * 4, TARGET_REPORT_ITEMS * 2),
    )
    existing_urls = {item.get("url", "") for item in eligible_items}
    supplement_items = [item for item in stored_items if item.get("url", "") not in existing_urls]

    needed = max(TARGET_REPORT_ITEMS - len(eligible_items), 0)
    if needed == 0:
        needed = min(len(supplement_items), max(report_top_n, MIN_LOW_PRIORITY_ITEMS))

    chosen_supplements = supplement_items[:needed]
    return eligible_items + chosen_supplements, len(chosen_supplements)


def fallback_with_current_cards(
    eligible_items: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    report_top_n: int,
) -> tuple[list[dict[str, Any]], int]:
    fallback_candidates = [
        item
        for item in cards
        if (
            item.get("is_ai_related", True)
            or item.get("importance_score", 0) >= 20
            or item.get("source_type") in {"official", "open_source", "research", "product", "media"}
        )
    ]
    existing_urls = {item.get("url", "") for item in eligible_items}
    supplements = [item for item in fallback_candidates if item.get("url", "") not in existing_urls]
    needed = max(TARGET_REPORT_ITEMS - len(eligible_items), 0)
    if needed <= 0:
        needed = max(MIN_LOW_PRIORITY_ITEMS, 0)
    chosen = supplements[: max(needed, MIN_REPORT_ITEMS - len(eligible_items), 0)]
    return eligible_items + chosen, len(chosen)


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
    daily_editor = DailyEditor(api_key=settings.openai_api_key, model=settings.openai_model)

    logger.info("开始抓取资讯源...")
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
    existing_recent_urls: list[str] = []
    for item in recent_items:
        if repository.exists_by_url(item["url"]):
            existing_recent_urls.append(item["url"])
            continue
        filtered_items.append(item)
    logger.info("过滤数据库中已存在 URL 后条数: %s", len(filtered_items))

    existing_recent_items = repository.get_items_by_urls(existing_recent_urls, limit=max(TARGET_REPORT_ITEMS * 3, settings.report_top_n * 3))
    logger.info("从数据库回收已存在近期条数: %s", len(existing_recent_items))

    unique_items = dedupe_items(filtered_items)
    logger.info("去重后条数: %s", len(unique_items))

    classified_items = classify_items(unique_items)

    cards: list[dict[str, Any]] = []
    processed_count = 0
    for item in sort_items_by_priority(classified_items, settings.report_timezone):
        article_id = repository.insert_article(item)
        card = {**item, **summarizer.summarize_item(item)}
        repository.insert_article_summary(article_id, card)
        cards.append(card)
        processed_count += 1

    new_eligible_items = [
        item
        for item in cards
        if (
            item.get("is_ai_related", True)
            or item.get("source_type") in {"official", "open_source", "research", "product", "media"}
        )
        and (
            item.get("include_in_report", False)
            or item.get("importance_score", 0) >= REGULAR_THRESHOLD
            or item.get("importance_score", 0) >= 25
            or item.get("source_type") in {"official", "open_source", "research"}
        )
    ]
    eligible_items = dedupe_items(existing_recent_items + new_eligible_items)

    db_supplement_count = 0
    if len(eligible_items) < TARGET_REPORT_ITEMS:
        logger.info("本次可用条目偏少，尝试从数据库补足最近 %s 天内容。", settings.recent_days)
        eligible_items, db_supplement_count = supplement_with_recent_database_items(
            repository=repository,
            eligible_items=eligible_items,
            recent_days=settings.recent_days,
            report_top_n=settings.report_top_n,
        )

    current_card_fallback_count = 0
    if len(eligible_items) < TARGET_REPORT_ITEMS:
        logger.info("可用条目仍然偏少，补充当日已处理卡片。")
        eligible_items, current_card_fallback_count = fallback_with_current_cards(
            eligible_items=eligible_items,
            cards=cards,
            report_top_n=settings.report_top_n,
        )

    top_items, section_items, low_priority_items = partition_items(eligible_items)
    included_items = top_items + [item for items in section_items.values() for item in items] + low_priority_items

    stats = {
        "fetched_count": len(raw_items),
        "normalized_count": len(normalized_items),
        "deduped_count": len(unique_items),
        "processed_count": processed_count,
        "top_count": len(top_items),
        "regular_count": sum(len(items) for items in section_items.values()),
        "low_priority_count": len(low_priority_items),
        "included_count": len(included_items),
        "db_supplement_count": db_supplement_count,
        "current_card_fallback_count": current_card_fallback_count,
    }

    editorial_summary = daily_editor.build_daily_summary(included_items, stats)

    report_markdown = build_daily_report(
        top_items=top_items,
        section_items=section_items,
        low_priority_items=low_priority_items,
        editorial_summary=editorial_summary,
        stats=stats,
        timezone_name=settings.report_timezone,
    )

    report_path = write_markdown_report(
        content=report_markdown,
        output_dir="reports",
        timezone_name=settings.report_timezone,
    )
    repository.insert_report(report_path=report_path, item_count=len(included_items))

    stats["report_path"] = str(report_path)
    logger.info("处理完成: %s", stats)
    return stats


def main() -> None:
    try:
        stats = run_pipeline()
        print("\n=== AI Daily Scout ===")
        print(f"抓取条数: {stats['fetched_count']}")
        print(f"标准化后条数: {stats['normalized_count']}")
        print(f"去重后条数: {stats['deduped_count']}")
        print(f"模型处理条数: {stats['processed_count']}")
        print(f"收录到重点区条数: {stats['top_count']}")
        print(f"收录到普通区条数: {stats['regular_count']}")
        print(f"低优先级简讯条数: {stats['low_priority_count']}")
        print(f"数据库补足条数: {stats['db_supplement_count']}")
        print(f"当日卡片兜底条数: {stats['current_card_fallback_count']}")
        print(f"最终日报路径: {stats['report_path']}")
    except Exception as exc:
        logger.exception("主流程运行失败: %s", exc)
        raise


if __name__ == "__main__":
    main()
