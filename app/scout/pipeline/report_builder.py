from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


SECTION_ORDER = [
    ("产品与应用", {"产品", "应用"}),
    ("模型 / 开源 / 技术", {"开源"}),
    ("公司动态 / 融资", {"融资/公司动态"}),
    ("研究 / 新闻 / 其他", {"研究", "新闻", "其他"}),
]

SOURCE_TYPE_LABELS = {
    "official_global": "国际官方发布",
    "official_china": "中国官方发布",
    "product_discovery": "产品发现",
    "open_source": "开源生态",
    "research": "研究趋势",
    "media_global": "国际媒体报道",
    "media_china": "中文媒体报道",
    "official": "官方发布",
    "product": "产品发现",
    "media": "媒体报道",
}


def build_daily_report(
    *,
    top_items: list[dict[str, Any]],
    section_items: dict[str, list[dict[str, Any]]],
    low_priority_items: list[dict[str, Any]],
    editorial_summary: dict[str, Any],
    stats: dict[str, Any],
    timezone_name: str,
) -> str:
    tz = ZoneInfo(timezone_name)
    report_date = datetime.now(tz).date().isoformat()
    all_items = top_items + [item for items in section_items.values() for item in items] + low_priority_items
    category_counter = Counter(item.get("category_suggestion") or item.get("category") or "其他" for item in all_items)
    tag_counter = Counter(tag for item in all_items for tag in item.get("tags", []))
    source_type_counter = Counter(item.get("source_type") or "unknown" for item in all_items)

    top_categories = "、".join(name for name, _ in category_counter.most_common(3)) or "产品、应用、研究"
    top_tags = "、".join(name for name, _ in tag_counter.most_common(5)) or "AI产品、开发者工具、大模型"
    top_source_types = "、".join(
        SOURCE_TYPE_LABELS.get(name, name) for name, _ in source_type_counter.most_common(3)
    ) or "官方发布、研究趋势、媒体报道"

    lines = [
        f"# AI Daily Scout 日报 | {report_date}",
        "",
        "## 今日概览",
        f"- 今日共抓取 **{stats.get('fetched_count', 0)}** 条资讯，去重后 **{stats.get('deduped_count', 0)}** 条，最终收录 **{stats.get('included_count', 0)}** 条。",
        f"- 资讯主要集中在：{top_categories}",
        f"- 今日高频关键词：{top_tags}",
        f"- 今日主要来源类型：{top_source_types}",
        f"- 主编摘要：{editorial_summary.get('overview', '今天 AI 动态仍以产品、应用和模型能力更新为主。')}",
        "",
    ]

    if top_items:
        lines.extend(["## 今日重点 Top 3", ""])
        for index, item in enumerate(top_items[:3], start=1):
            lines.extend(render_featured_item(index, item, all_items))

    for section_name, categories in SECTION_ORDER:
        items = []
        for category in categories:
            items.extend(section_items.get(category, []))
        if not items:
            continue
        lines.extend([f"## {section_name}", ""])
        section_rendered_urls: set[str] = set()
        for source_type, grouped_items in group_by_source_type(items).items():
            lines.extend([f"### {SOURCE_TYPE_LABELS.get(source_type, source_type)}", ""])
            rendered_items = grouped_items[: min(3, len(grouped_items))]
            for item in rendered_items:
                lines.extend(render_section_item(item, all_items))
                if item.get("url"):
                    section_rendered_urls.add(item["url"])
            lines.extend(render_link_roundup(grouped_items, rendered_urls=section_rendered_urls))
        if section_name == "研究 / 新闻 / 其他":
            lines.extend(render_quick_links_block(items, low_priority_items, rendered_urls=section_rendered_urls))

    trend_observations = editorial_summary.get("trend_observations", [])
    if trend_observations:
        lines.extend(["## 今日趋势观察", ""])
        lines.extend([f"- {item}" for item in trend_observations[:4]])
        lines.append("")

    follow_up_topics = editorial_summary.get("follow_up_topics", [])
    if follow_up_topics:
        lines.extend(["## 值得继续跟踪的话题", ""])
        lines.extend([f"- {item}" for item in follow_up_topics[:3]])
        lines.append("")

    if low_priority_items:
        lines.extend(["## 低优先级简讯", ""])
        for item in low_priority_items[:12]:
            lines.append(
                f"- **{item.get('zh_title') or item.get('title')}**："
                f"{item.get('one_line_takeaway') or item.get('short_summary')} "
                f"[原文]({item.get('url') or ''})"
            )
        lines.append("")

    low_priority_summary = editorial_summary.get("low_priority_summary", "")
    if low_priority_summary:
        lines.extend(["## 主编补充观察", "", low_priority_summary, ""])

    return "\n".join(lines).strip() + "\n"


def render_featured_item(index: int, item: dict[str, Any], all_items: list[dict[str, Any]]) -> list[str]:
    lines = [
        f"### {index}. {item.get('zh_title') or item.get('title')}",
        f"- **摘要：** {build_item_summary(item)}",
        f"- **为什么重要：** {item.get('why_it_matters') or '信息不足'}",
        f"- **谁应该关注：** {item.get('who_should_care') or '信息不足'}",
        f"- **简评：** {item.get('my_commentary') or '信息不足'}",
        f"- **来源：** {item.get('source') or '未知来源'}",
        f"- **来源类型：** `{item.get('source_type') or 'unknown'}`",
        f"- **原文链接：** [原文]({item.get('url') or ''})",
    ]
    lines.extend(render_extended_links(item, label="延伸阅读", fallback_items=all_items, minimum_links=2, maximum_links=4))
    lines.extend(["", "---", ""])
    return lines


def render_section_item(item: dict[str, Any], all_items: list[dict[str, Any]]) -> list[str]:
    lines = [
        f"#### {item.get('zh_title') or item.get('title')}",
        f"- **摘要：** {build_item_summary(item)}",
        f"- **为什么值得看：** {item.get('why_it_matters') or '信息不足'}",
        f"- **适合人群：** {item.get('who_should_care') or '信息不足'}",
        f"- **来源：** {item.get('source') or '未知来源'}",
        f"- **原文链接：** [原文]({item.get('url') or ''})",
    ]
    lines.extend(render_extended_links(item, label="更多链接", fallback_items=all_items, minimum_links=1, maximum_links=3))
    lines.extend(["", "---", ""])
    return lines


def render_extended_links(
    item: dict[str, Any],
    label: str,
    *,
    fallback_items: list[dict[str, Any]],
    minimum_links: int,
    maximum_links: int,
) -> list[str]:
    links = build_link_suggestions(item, fallback_items, maximum_links=maximum_links)
    if len(links) < minimum_links:
        return []
    link_text = "；".join(f"[{entry['label']}]({entry['url']})" for entry in links[:maximum_links])
    return [f"- **{label}：** {link_text}"]


def render_link_roundup(items: list[dict[str, Any]], *, rendered_urls: set[str]) -> list[str]:
    links: list[str] = []
    seen_urls = set(rendered_urls)

    for item in items:
        url = str(item.get("url", "")).strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            links.append(f"- [{item.get('zh_title') or item.get('title')}]({url})")
        for source in item.get("related_sources", []):
            related_url = str(source.get("url", "")).strip()
            if not related_url or related_url in seen_urls:
                continue
            seen_urls.add(related_url)
            label = source.get("source") or source.get("title") or "相关来源"
            links.append(f"- [{label}]({related_url})")
        if len(links) >= 12:
            break

    if not links:
        return []

    lines = ["**资讯链接速览：**"]
    lines.extend(links[:12])
    lines.append("")
    return lines


def render_quick_links_block(
    section_items: list[dict[str, Any]],
    low_priority_items: list[dict[str, Any]],
    *,
    rendered_urls: set[str],
) -> list[str]:
    section_categories = {"研究", "新闻", "其他"}
    quick_candidates = [
        item
        for item in low_priority_items
        if (item.get("category_suggestion") or item.get("category") or "其他") in section_categories
    ]
    if not quick_candidates:
        quick_candidates = [
            item
            for item in section_items
            if item.get("url") and item.get("url") not in rendered_urls
        ]

    quick_items = sorted(
        quick_candidates,
        key=lambda item: (int(item.get("importance_score", 0)), int(item.get("priority", 50))),
        reverse=True,
    )[:12]
    if not quick_items:
        return []

    lines = ["### 更多快讯链接", ""]
    seen_urls = set(rendered_urls)
    added = 0
    for item in quick_items:
        url = str(item.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        source = item.get("source") or "未知来源"
        title = item.get("zh_title") or item.get("title") or "未命名条目"
        lines.append(f"- [{title}]({url}) - {source}")
        added += 1
        if added >= 12:
            break
    if added == 0:
        return []
    lines.append("")
    return lines


def group_by_source_type(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = item.get("source_type") or "unknown"
        grouped.setdefault(key, []).append(item)
    return grouped


def build_link_suggestions(
    item: dict[str, Any],
    fallback_items: list[dict[str, Any]],
    *,
    maximum_links: int,
) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for source in item.get("related_sources", []):
        url = str(source.get("url", "")).strip()
        if not url or url == item.get("url") or url in seen_urls:
            continue
        seen_urls.add(url)
        suggestions.append(
            {
                "label": source.get("source") or source.get("title") or "相关来源",
                "url": url,
            }
        )
        if len(suggestions) >= maximum_links:
            return suggestions

    item_category = item.get("category_suggestion") or item.get("category")
    item_source_type = item.get("source_type")
    fallback_candidates = [
        candidate
        for candidate in fallback_items
        if str(candidate.get("url", "")).strip()
        and str(candidate.get("url", "")).strip() != item.get("url")
        and (
            (candidate.get("category_suggestion") or candidate.get("category")) == item_category
            or candidate.get("source_type") == item_source_type
        )
    ]
    if len(fallback_candidates) < 2:
        return suggestions

    for candidate in fallback_candidates:
        candidate_url = str(candidate.get("url", "")).strip()
        if not candidate_url or candidate_url == item.get("url") or candidate_url in seen_urls:
            continue
        seen_urls.add(candidate_url)
        suggestions.append(
            {
                "label": candidate.get("zh_title") or candidate.get("title") or candidate.get("source") or "相关条目",
                "url": candidate_url,
            }
        )
        if len(suggestions) >= maximum_links:
            break

    return suggestions


def build_item_summary(item: dict[str, Any]) -> str:
    summary = (
        item.get("what_happened")
        or item.get("short_summary")
        or item.get("summary")
        or item.get("one_line_takeaway")
        or "信息不足"
    )
    return str(summary).strip() or "信息不足"
