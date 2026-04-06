from __future__ import annotations

from collections import Counter, defaultdict
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

TARGET_REPORT_ITEMS = 18
MIN_SECTION_ITEMS = 3
TOP_ITEM_MIN_QUALITY = 65
TOP_ITEM_MIN_SUMMARY_QUALITY = 60

SECTION_ORDER = ["产品与应用", "公司动态", "研究与趋势"]
SECTION_SET = set(SECTION_ORDER)

CORE_SOURCE_TYPES = {
    "official_global",
    "official_china",
    "product_discovery",
    "open_source",
    "research",
    "media_global",
    "media_china",
    "official",
    "product",
    "media",
}
HIGH_TRUST_SOURCE_TYPES = {"official_global", "official_china", "open_source", "research", "official"}

TOPIC_PRIORITY_KEYWORDS = {
    "agent": 20,
    "enterprise": 16,
    "tooling": 16,
    "coding": 14,
    "multimodal": 14,
    "paper": 12,
    "benchmark": 12,
    "model": 10,
    "company": 10,
    "funding": 14,
}


def has_complete_model_summary(item: dict[str, Any]) -> bool:
    if not item.get("generated_by_model"):
        return False
    summary = str(item.get("what_happened") or item.get("summary_zh") or "").strip()
    return len(summary) >= 60


def ensure_directories() -> None:
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("reports").mkdir(parents=True, exist_ok=True)


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


def filter_recent_items(items: list[dict[str, Any]], recent_days: int, timezone_name: str) -> list[dict[str, Any]]:
    if recent_days <= 0:
        return items
    tz = ZoneInfo(timezone_name)
    cutoff = datetime.now(tz) - timedelta(days=recent_days)
    filtered: list[dict[str, Any]] = []
    for item in items:
        published_at = parse_datetime(str(item.get("published_at", "")), tz)
        if published_at is None or published_at >= cutoff:
            filtered.append(item)
    return filtered


def sort_items_by_priority(items: list[dict[str, Any]], timezone_name: str) -> list[dict[str, Any]]:
    tz = ZoneInfo(timezone_name)
    return sorted(
        items,
        key=lambda item: (
            float(item.get("editorial_score", 0)),
            int(item.get("importance_score", 0)),
            int(item.get("quality_score", 0)),
            parse_datetime(str(item.get("published_at", "")), tz) or datetime.min.replace(tzinfo=tz),
        ),
        reverse=True,
    )


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
    existing_urls = {str(item.get("url", "")) for item in eligible_items}
    supplement_items = [item for item in stored_items if str(item.get("url", "")) not in existing_urls]
    needed = max(TARGET_REPORT_ITEMS - len(eligible_items), 0)
    chosen = supplement_items[:needed]
    return eligible_items + chosen, len(chosen)


def fallback_with_current_cards(
    eligible_items: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    existing_urls = {str(item.get("url", "")) for item in eligible_items}
    supplements = [item for item in cards if str(item.get("url", "")) not in existing_urls]
    needed = max(TARGET_REPORT_ITEMS - len(eligible_items), 0)
    chosen = supplements[:needed]
    return eligible_items + chosen, len(chosen)


def refresh_editorial_cards(
    repository: ArticleRepository,
    summarizer: NewsSummarizer,
    items: list[dict[str, Any]],
    refresh_limit: int,
    timezone_name: str,
) -> tuple[list[dict[str, Any]], int]:
    refreshed = 0
    refreshed_items: list[dict[str, Any]] = []
    for item in sort_items_by_priority(items, timezone_name):
        current_item = item
        if refreshed < refresh_limit and not has_complete_model_summary(item):
            article_id = repository.get_article_id_by_url(str(item.get("url", "")))
            if article_id:
                updated_card = enrich_item_for_report({**item, **summarizer.summarize_item(item)}, timezone_name)
                repository.insert_article_summary(article_id, updated_card)
                current_item = updated_card
                refreshed += 1
        refreshed_items.append(current_item)
    return refreshed_items, refreshed


def pick_display_summary(item: dict[str, Any]) -> str:
    for key in ("summary_zh", "one_line_takeaway", "short_summary", "summary", "what_happened"):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    return ""


def resolve_display_section(item: dict[str, Any]) -> str:
    source = str(item.get("source_name") or item.get("source") or "").lower()
    source_type = str(item.get("source_type") or "").lower()
    title = str(item.get("display_title") or item.get("clean_title") or item.get("title") or "").lower()
    summary = pick_display_summary(item).lower()
    text = " ".join([source, source_type, title, summary])
    url = str(item.get("canonical_url") or item.get("url") or "").lower()

    if "hugging face papers" in source or "arxiv" in source:
        return "研究与趋势"
    if "github.com" in url:
        if any(token in text for token in ("paper", "benchmark", "research", "eval", "dataset")):
            return "研究与趋势"
        return "产品与应用"
    if any(
        token in text
        for token in (
            "funding",
            "raise",
            "raised",
            "acquisition",
            "acquire",
            "partnership",
            "pricing",
            "price",
            "mou",
            "融资",
            "收购",
            "合作",
            "定价",
            "announces",
            "announcement",
        )
    ):
        return "公司动态"
    if any(
        token in text
        for token in (
            "paper",
            "benchmark",
            "research",
            "method",
            "dataset",
            "arxiv",
            "论文",
            "评测",
            "研究",
        )
    ):
        return "研究与趋势"
    if any(
        token in text
        for token in (
            "launch",
            "release",
            "feature",
            "product",
            "tool",
            "sdk",
            "api",
            "copilot",
            "assistant",
            "agent",
            "workflow",
            "应用",
            "工具",
            "上线",
            "发布",
        )
    ):
        return "产品与应用"
    if source_type == "research":
        return "研究与趋势"
    if source_type in {"open_source", "product_discovery", "product"}:
        return "产品与应用"
    if source_type in {"official_global", "official_china", "official"}:
        return "公司动态"
    return "研究与趋势"


def derive_topic_tags(item: dict[str, Any]) -> list[str]:
    original_tags = [str(tag).strip().lower() for tag in item.get("topic_tags", []) or item.get("tags", []) if str(tag).strip()]
    text = " ".join(
        [
            str(item.get("display_title", "")),
            str(item.get("clean_title", "")),
            str(item.get("title", "")),
            pick_display_summary(item),
        ]
    ).lower()
    inferred: list[str] = []
    if "agent" in text or "智能体" in text:
        inferred.append("agent")
    if any(keyword in text for keyword in ("enterprise", "workflow", "企业", "业务")):
        inferred.append("enterprise")
    if any(keyword in text for keyword in ("developer", "sdk", "api", "cli", "copilot", "coding", "编程", "framework", "toolkit")):
        inferred.extend(["tooling", "coding"])
    if any(keyword in text for keyword in ("multimodal", "video", "image", "audio", "视觉", "多模态")):
        inferred.append("multimodal")
    if any(keyword in text for keyword in ("model", "llm", "gpt", "claude", "qwen", "模型")):
        inferred.append("model")
    if any(keyword in text for keyword in ("paper", "arxiv", "benchmark", "research", "论文", "评测")):
        inferred.extend(["paper", "benchmark"])
    if any(keyword in text for keyword in ("funding", "raise", "acquisition", "pricing", "partnership", "融资", "收购", "合作", "定价")):
        inferred.extend(["company", "funding"])
    if "github.com" in str(item.get("url", "")).lower():
        inferred.append("tooling")

    result: list[str] = []
    seen: set[str] = set()
    for tag in original_tags + inferred:
        if tag not in seen:
            result.append(tag)
            seen.add(tag)
    return result[:6]


def compute_quality_score(item: dict[str, Any]) -> int:
    score = 40
    title = str(item.get("display_title") or item.get("clean_title") or item.get("title") or "").strip()
    summary = pick_display_summary(item)
    source_type = str(item.get("source_type", "")).strip()
    if 8 <= len(title) <= 100:
        score += 10
    if summary:
        score += min(20, len(summary) // 12)
    score += min(18, int(item.get("summary_quality", 0)) // 5)
    if source_type in HIGH_TRUST_SOURCE_TYPES:
        score += 12
    if item.get("generated_by_model"):
        score += 8
    if item.get("related_sources"):
        score += 5
    if any(bad in title.lower() for bad in ("giveaway", "casino", "click here", "subscribe")):
        score -= 30
    return max(0, min(score, 100))


def compute_editorial_score(item: dict[str, Any], timezone: ZoneInfo) -> float:
    source_authority = source_authority_score(item)
    freshness = freshness_score(item, timezone)
    topic_priority = topic_priority_score(item)
    originality = originality_score(item)
    applicability = applicability_score(item)
    return round(
        0.30 * source_authority
        + 0.20 * freshness
        + 0.20 * topic_priority
        + 0.15 * originality
        + 0.15 * applicability,
        2,
    )


def source_authority_score(item: dict[str, Any]) -> int:
    mapping = {
        "official_global": 95,
        "official_china": 92,
        "research": 88,
        "open_source": 84,
        "media_global": 76,
        "media_china": 70,
        "product_discovery": 68,
        "official": 88,
        "product": 72,
        "media": 66,
    }
    return mapping.get(str(item.get("source_type", "")).strip(), 60)


def freshness_score(item: dict[str, Any], timezone: ZoneInfo) -> int:
    published_at = parse_datetime(str(item.get("published_at", "")), timezone)
    if published_at is None:
        return 55
    age_hours = max((datetime.now(timezone) - published_at).total_seconds() / 3600, 0)
    if age_hours <= 24:
        return 95
    if age_hours <= 72:
        return 80
    if age_hours <= 168:
        return 60
    return 40


def topic_priority_score(item: dict[str, Any]) -> int:
    score = 55
    for tag in item.get("topic_tags", []) or []:
        score += TOPIC_PRIORITY_KEYWORDS.get(str(tag).lower(), 0)
    return min(score, 100)


def originality_score(item: dict[str, Any]) -> int:
    source_type = str(item.get("source_type", "")).strip()
    related_count = len(item.get("related_sources", []) or item.get("related_links", []) or [])
    base = 60
    if source_type in {"official_global", "official_china", "research", "open_source"}:
        base = 88
    elif source_type in {"media_global", "media_china"}:
        base = 68
    if related_count >= 3:
        base += 5
    return min(base, 100)


def applicability_score(item: dict[str, Any]) -> int:
    section = str(item.get("display_section", "")).strip()
    if section == "产品与应用":
        return 90
    if section == "公司动态":
        return 74
    if section == "研究与趋势":
        return 70
    return 65


def detect_trend_type(item: dict[str, Any], timezone: ZoneInfo) -> str:
    published_at = parse_datetime(str(item.get("published_at", "")), timezone)
    if published_at is None:
        return "trending"
    now = datetime.now(timezone)
    age_days = (now.date() - published_at.date()).days
    source_type = str(item.get("source_type", "")).strip()
    if age_days <= 1:
        return "new_release"
    if age_days <= 7:
        return "trending"
    if source_type in {"research", "open_source"}:
        return "evergreen"
    return "recap"


def normalize_target_audience(value: Any) -> list[str]:
    if not value:
        return []
    text = str(value).replace("、", ",").replace("，", ",")
    return [part.strip() for part in text.split(",") if part.strip()][:4]


def is_top_item_eligible(item: dict[str, Any]) -> bool:
    display_title = str(item.get("display_title") or item.get("clean_title") or item.get("title") or "").strip()
    summary = pick_display_summary(item)
    section = str(item.get("display_section") or "").strip()
    return (
        len(display_title) >= 6
        and len(summary) >= 20
        and int(item.get("summary_quality", 0)) >= TOP_ITEM_MIN_SUMMARY_QUALITY
        and int(item.get("quality_score", 0)) >= TOP_ITEM_MIN_QUALITY
        and section in SECTION_SET
    )


def choose_top_items(items: list[dict[str, Any]], settings: Any, timezone_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    remainder: list[dict[str, Any]] = []
    source_counter: Counter[str] = Counter()
    topic_counter: Counter[str] = Counter()
    section_counter: Counter[str] = Counter()
    target_count = settings.newsletter_max_top_items

    for item in sort_items_by_priority(items, timezone_name):
        if not is_top_item_eligible(item):
            remainder.append(item)
            continue

        source = str(item.get("source", "")).strip()
        section = str(item.get("display_section", "")).strip()
        primary_topic = next(iter(item.get("topic_tags", []) or []), "")

        source_ok = source_counter[source] < settings.newsletter_max_items_per_source_in_top if source else True
        topic_ok = topic_counter[primary_topic] < settings.newsletter_max_items_per_topic_in_top if primary_topic else True
        section_ok = True
        if len(selected) < target_count and section_counter["产品与应用"] == 0 and len(selected) >= target_count - 1:
            section_ok = section == "产品与应用"

        if len(selected) < target_count and source_ok and topic_ok and section_ok:
            selected.append(item)
            if source:
                source_counter[source] += 1
            if primary_topic:
                topic_counter[primary_topic] += 1
            if section:
                section_counter[section] += 1
        else:
            remainder.append(item)

    if len(selected) < target_count:
        refill: list[dict[str, Any]] = []
        next_remainder: list[dict[str, Any]] = []
        for item in remainder:
            if len(selected) + len(refill) >= target_count:
                next_remainder.append(item)
                continue
            if str(item.get("display_section") or "").strip() in SECTION_SET and int(item.get("quality_score", 0)) >= TOP_ITEM_MIN_QUALITY - 5:
                refill.append(item)
            else:
                next_remainder.append(item)
        selected.extend(refill)
        remainder = next_remainder

    return selected[:target_count], remainder + selected[target_count:]


def build_sections(
    items: list[dict[str, Any]],
    settings: Any,
    timezone_name: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    quick_hits: list[dict[str, Any]] = []
    for item in sort_items_by_priority(items, timezone_name):
        section = str(item.get("display_section") or "研究与趋势")
        if int(item.get("quality_score", 0)) < 45 or int(item.get("importance_score", 0)) < 45:
            quick_hits.append(item)
            continue
        if section in SECTION_SET:
            grouped[section].append(item)
        else:
            quick_hits.append(item)

    section_items: dict[str, list[dict[str, Any]]] = {}
    for section in SECTION_ORDER:
        candidates = grouped.get(section, [])
        if len(candidates) < MIN_SECTION_ITEMS:
            deficit = MIN_SECTION_ITEMS - len(candidates)
            borrowed = quick_hits[:deficit]
            quick_hits = quick_hits[deficit:]
            candidates = candidates + borrowed
        section_items[section] = candidates[:4]

    seen_urls = {str(item.get("url", "")) for items_in_section in section_items.values() for item in items_in_section}
    quick_hits = [item for item in quick_hits if str(item.get("url", "")) not in seen_urls]
    return section_items, quick_hits[: settings.newsletter_max_quick_hits]


def enrich_item_for_report(item: dict[str, Any], timezone_name: str) -> dict[str, Any]:
    tz = ZoneInfo(timezone_name)
    enriched = {**item}
    if not enriched.get("clean_title"):
        enriched["clean_title"] = item.get("zh_title") or item.get("title") or ""
    if not enriched.get("display_title"):
        enriched["display_title"] = item.get("clean_title") or item.get("zh_title") or item.get("title") or ""
    if not enriched.get("canonical_url"):
        enriched["canonical_url"] = item.get("url", "")
    if not enriched.get("published_date"):
        enriched["published_date"] = str(item.get("published_at", ""))[:10]
    if not enriched.get("related_links"):
        enriched["related_links"] = item.get("related_sources", [])
    if not enriched.get("target_audience_zh"):
        enriched["target_audience_zh"] = normalize_target_audience(item.get("who_should_care"))
    enriched["summary_zh"] = pick_display_summary(item)
    enriched["raw_title"] = item.get("raw_title") or item.get("title") or ""
    enriched["raw_summary"] = item.get("raw_summary") or item.get("summary") or ""
    enriched["display_section"] = resolve_display_section(enriched)
    enriched["trend_type"] = detect_trend_type(enriched, tz)
    enriched["topic_tags"] = derive_topic_tags(enriched)
    enriched["quality_score"] = compute_quality_score(enriched)
    enriched["editorial_score"] = compute_editorial_score(enriched, tz)
    return enriched


def run_pipeline() -> dict[str, Any]:
    settings = get_settings()
    ensure_directories()
    init_db(settings.database_path)

    repository = ArticleRepository(settings.database_path)
    summarizer = NewsSummarizer(
        api_key=settings.llm_api_key,
        model=settings.openai_model,
        language=settings.report_language,
        base_url=settings.llm_base_url,
    )
    daily_editor = DailyEditor(
        api_key=settings.llm_api_key,
        model=settings.openai_model,
        base_url=settings.llm_base_url,
    )

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

    existing_recent_items = repository.get_items_by_urls(
        existing_recent_urls,
        limit=max(TARGET_REPORT_ITEMS * 4, settings.report_top_n * 4),
    )
    existing_recent_items = [enrich_item_for_report(item, settings.report_timezone) for item in existing_recent_items]
    logger.info("从数据库回收已存在近期条数: %s", len(existing_recent_items))

    unique_items = dedupe_items(filtered_items)
    logger.info("去重后候选条数: %s", len(unique_items))

    classified_items = classify_items(unique_items)

    cards: list[dict[str, Any]] = []
    processed_count = 0
    for item in classified_items:
        article_id = repository.insert_article(item)
        card = enrich_item_for_report({**item, **summarizer.summarize_item(item)}, settings.report_timezone)
        repository.insert_article_summary(article_id, card)
        cards.append(card)
        processed_count += 1

    eligible_items = [
        item
        for item in dedupe_items(existing_recent_items + cards)
        if (
            item.get("is_ai_related", True) or item.get("source_type") in CORE_SOURCE_TYPES
        )
        and (
            item.get("include_in_report", False)
            or item.get("source_type") in HIGH_TRUST_SOURCE_TYPES
            or int(item.get("quality_score", 0)) >= 55
            or float(item.get("editorial_score", 0)) >= 70
        )
    ]

    db_supplement_count = 0
    if len(eligible_items) < TARGET_REPORT_ITEMS:
        eligible_items, db_supplement_count = supplement_with_recent_database_items(
            repository=repository,
            eligible_items=eligible_items,
            recent_days=settings.recent_days,
            report_top_n=settings.report_top_n,
        )
        eligible_items = [enrich_item_for_report(item, settings.report_timezone) for item in eligible_items]

    current_card_fallback_count = 0
    if len(eligible_items) < TARGET_REPORT_ITEMS:
        eligible_items, current_card_fallback_count = fallback_with_current_cards(eligible_items, cards)
        eligible_items = [enrich_item_for_report(item, settings.report_timezone) for item in eligible_items]

    refreshed_summary_count = 0
    if eligible_items:
        eligible_items, refreshed_summary_count = refresh_editorial_cards(
            repository=repository,
            summarizer=summarizer,
            items=eligible_items,
            refresh_limit=max(settings.report_top_n * 2, 8),
            timezone_name=settings.report_timezone,
        )

    top_items, remaining_items = choose_top_items(eligible_items, settings, settings.report_timezone)
    section_items, low_priority_items = build_sections(remaining_items, settings, settings.report_timezone)

    final_items = top_items + [item for section in SECTION_ORDER for item in section_items.get(section, [])] + low_priority_items
    final_items = dedupe_items(final_items)
    final_urls = {str(item.get("url", "")) for item in final_items}
    top_items = [item for item in top_items if str(item.get("url", "")) in final_urls][: settings.newsletter_max_top_items]
    for section in SECTION_ORDER:
        section_items[section] = [item for item in section_items.get(section, []) if str(item.get("url", "")) in final_urls]
    low_priority_items = [item for item in low_priority_items if str(item.get("url", "")) in final_urls][: settings.newsletter_max_quick_hits]

    stats = {
        "raw_count": len(raw_items),
        "normalized_count": len(normalized_items),
        "filtered_count": len(filtered_items),
        "dedup_count": len(unique_items),
        "processed_count": processed_count,
        "top_count": len(top_items),
        "final_count": len(final_items),
        "included_count": len(final_items),
        "db_supplement_count": db_supplement_count,
        "current_card_fallback_count": current_card_fallback_count,
        "refreshed_summary_count": refreshed_summary_count,
    }

    editorial_summary = daily_editor.build_daily_summary(final_items, stats)
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
    repository.insert_report(report_path=report_path, item_count=len(final_items))

    stats["report_path"] = str(report_path)
    logger.info("处理完成: %s", stats)
    return stats


def main() -> None:
    try:
        stats = run_pipeline()
        print("\n=== AI Daily Scout ===")
        print(f"抓取总量: {stats['raw_count']}")
        print(f"最终收录量: {stats['final_count']}")
        print(f"重点推荐量: {stats['top_count']}")
        print(f"最终日报路径: {stats['report_path']}")
    except Exception as exc:
        logger.exception("主流程运行失败: %s", exc)
        raise


if __name__ == "__main__":
    main()
