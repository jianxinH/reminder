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

    top_categories = "、".join(name for name, _ in category_counter.most_common(3)) or "产品、应用、研究"
    top_tags = "、".join(name for name, _ in tag_counter.most_common(5)) or "AI产品、开发者工具、大模型"

    lines = [
        f"# AI Daily Scout 日报 | {report_date}",
        "",
        "## 今日概览",
        f"- 今日共抓取 **{stats.get('fetched_count', 0)}** 条资讯，去重后 **{stats.get('deduped_count', 0)}** 条，最终收录 **{stats.get('included_count', 0)}** 条。",
        f"- 资讯主要集中在：{top_categories}",
        f"- 今日高频关键词：{top_tags}",
        f"- 主编摘要：{editorial_summary.get('overview', '今天 AI 动态仍以产品、应用和模型能力更新为主。')}",
        "",
    ]

    if top_items:
        lines.extend(["## 今日重点 Top 3", ""])
        for index, item in enumerate(top_items[:3], start=1):
            lines.extend(render_featured_item(index, item))

    for section_name, categories in SECTION_ORDER:
        items = []
        for category in categories:
            items.extend(section_items.get(category, []))
        if not items:
            continue
        lines.extend([f"## {section_name}", ""])
        for item in items:
            lines.extend(render_section_item(item))

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
        for item in low_priority_items[:10]:
            lines.append(
                f"- **{item.get('zh_title') or item.get('title')}**："
                f"{item.get('one_line_takeaway') or item.get('short_summary')}"
                f" [原文]({item.get('url') or ''})"
            )
        lines.append("")

    low_priority_summary = editorial_summary.get("low_priority_summary", "")
    if low_priority_summary:
        lines.extend(["## 主编补充观察", "", low_priority_summary, ""])

    return "\n".join(lines).strip() + "\n"


def render_featured_item(index: int, item: dict[str, Any]) -> list[str]:
    lines = [
        f"### {index}. {item.get('zh_title') or item.get('title')}",
        f"- **一句话结论：** {item.get('one_line_takeaway') or '信息不足'}",
        f"- **发生了什么：** {item.get('what_happened') or '信息不足'}",
        f"- **为什么重要：** {item.get('why_it_matters') or '信息不足'}",
        f"- **谁应该关注：** {item.get('who_should_care') or '信息不足'}",
        f"- **简评：** {item.get('my_commentary') or '信息不足'}",
        f"- **来源：** {item.get('source') or '未知来源'}",
        f"- **来源类型：** `{item.get('source_type') or 'unknown'}`",
        f"- **链接：** [原文]({item.get('url') or ''})",
    ]
    related_sources = item.get("related_sources", [])
    if related_sources:
        lines.append(
            "- **相关来源：** "
            + "；".join(
                f"[{source.get('source') or source.get('title') or '相关来源'}]({source.get('url', '')})"
                for source in related_sources[:5]
            )
        )
    lines.extend(["", "---", ""])
    return lines


def render_section_item(item: dict[str, Any]) -> list[str]:
    lines = [
        f"### {item.get('zh_title') or item.get('title')}",
        f"- **一句话结论：** {item.get('one_line_takeaway') or '信息不足'}",
        f"- **核心信息：** {item.get('what_happened') or '信息不足'}",
        f"- **为什么值得看：** {item.get('why_it_matters') or '信息不足'}",
        f"- **适合人群：** {item.get('who_should_care') or '信息不足'}",
        f"- **简评：** {item.get('my_commentary') or '信息不足'}",
        f"- **来源：** {item.get('source') or '未知来源'}",
        f"- **来源类型：** `{item.get('source_type') or 'unknown'}`",
        f"- **链接：** [原文]({item.get('url') or ''})",
    ]
    related_sources = item.get("related_sources", [])
    if related_sources:
        lines.append(
            "- **更多链接：** "
            + "；".join(
                f"[{source.get('source') or source.get('title') or '相关来源'}]({source.get('url', '')})"
                for source in related_sources[:5]
            )
        )
    lines.extend(["", "---", ""])
    return lines
