from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


FIXED_INTRO = "> 每天 3 分钟，快速看完当天值得关注的 AI 产品、开源、研究与行业动态。"
SECTION_ORDER = ["产品与应用", "公司动态", "研究与趋势"]


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
    regular_items = [item for section in SECTION_ORDER for item in section_items.get(section, [])]
    all_items = top_items + regular_items + low_priority_items

    topic_counter = Counter(tag for item in all_items for tag in item.get("topic_tags", []) or item.get("tags", []))
    main_topics = "、".join(name for name, _ in topic_counter.most_common(4)) or "Agent、企业级 AI、开发工具、多模态"
    editorial_judgment = choose_editorial_judgment(editorial_summary, all_items)

    lines = [
        f"# AI Daily Scout｜{report_date}",
        "",
        FIXED_INTRO,
        "",
        "## 今日概览",
        "",
        f"- 今日共抓取 AI 相关资讯 **{stats.get('raw_count', stats.get('fetched_count', 0))}** 条，经去重、聚类与质量筛选后，最终收录 **{stats.get('final_count', stats.get('included_count', 0))}** 条",
        f"- 今日关注主线：{main_topics}",
        f"- 编辑判断：{editorial_judgment}",
        "",
        "## 今日最值得看的 3 件事",
        "",
    ]

    if top_items:
        for index, item in enumerate(top_items[:3], start=1):
            lines.extend(render_top_item(index, item))
    else:
        lines.extend(["### 暂无重点条目", "今天没有足够高质量的重点内容进入 Top 3。", ""])

    for section in SECTION_ORDER:
        items = section_items.get(section, [])
        if not items:
            continue
        lines.extend([f"## {section}", ""])
        for item in items:
            lines.extend(render_section_item(item))

    if low_priority_items:
        lines.extend(["## 快讯速览", ""])
        for item in low_priority_items[:8]:
            lines.append(
                f"- **{item.get('zh_title') or item.get('clean_title') or item.get('title')}**："
                f"{build_quick_hint(item)} [原文]({item.get('url') or ''})"
            )
        lines.append("")

    lines.extend(
        [
            "## 今天怎么读",
            "",
            f"- 如果你更关心产品落地，优先看“产品与应用”和 Top 3 里的企业场景条目。",
            f"- 如果你在追踪行业变化，重点看“公司动态”和其中的合作、融资、平台动作。",
            f"- 如果你做模型、算法或开发工具，重点看“研究与趋势”和快讯里的高频主题：{main_topics}。",
            "",
            "## 备注",
            "",
            "- 文中“趋势上升”表示该内容在今日讨论度明显提升，并不一定是当天首次发布。",
            "- 日报已对同主题信息做聚合，默认保留更原始、信息更完整的来源作为主条目。",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def render_top_item(index: int, item: dict[str, Any]) -> list[str]:
    lines = [
        f"### {index}）{item.get('zh_title') or item.get('clean_title') or item.get('title')}",
        build_one_line_summary(item),
    ]
    trend_note = build_trend_note(item)
    if trend_note:
        lines.extend(["", trend_note])
    lines.extend(
        [
            f"**为什么值得看：** {build_reason_to_watch(item)}",
            f"**适合谁看：** {build_target_audience(item)}",
            f"**原文：** {item.get('url') or ''}",
            "",
        ]
    )
    return lines


def render_section_item(item: dict[str, Any]) -> list[str]:
    lines = [
        f"### {item.get('zh_title') or item.get('clean_title') or item.get('title')}",
        build_one_line_summary(item),
    ]
    trend_note = build_trend_note(item)
    if trend_note:
        lines.extend(["", trend_note])
    lines.extend(
        [
            f"**看点：** {build_reason_to_watch(item)}",
            f"**原文：** {item.get('url') or ''}",
            "",
        ]
    )
    return lines


def build_one_line_summary(item: dict[str, Any]) -> str:
    summary = (
        item.get("one_line_takeaway")
        or item.get("short_summary")
        or item.get("summary_zh")
        or item.get("summary")
        or item.get("what_happened")
        or "信息不足"
    )
    text = clean_text(summary)
    return trim_text(text, 70)


def build_reason_to_watch(item: dict[str, Any]) -> str:
    reason = item.get("why_it_matters") or infer_reason_from_item(item)
    return trim_text(clean_text(reason), 50)


def build_target_audience(item: dict[str, Any]) -> str:
    audience = item.get("who_should_care") or infer_audience_from_item(item)
    return trim_text(clean_text(audience), 40)


def build_quick_hint(item: dict[str, Any]) -> str:
    hint = item.get("one_line_takeaway") or item.get("summary") or "今日值得顺手关注"
    return trim_text(clean_text(hint), 20)


def build_trend_note(item: dict[str, Any]) -> str:
    trend_type = str(item.get("trend_type", "")).strip()
    if trend_type == "trending":
        return "注：该内容为当日趋势上升，并非当日首次发布。"
    if trend_type == "recap":
        return "注：该内容更偏复盘与延续性进展，适合作为背景跟踪。"
    if trend_type == "evergreen":
        return "注：该内容并非当天新发，但今天仍具有较高参考价值。"
    return ""


def choose_editorial_judgment(editorial_summary: dict[str, Any], items: list[dict[str, Any]]) -> str:
    overview = clean_text(editorial_summary.get("overview"))
    if overview and len(overview) >= 20:
        first_sentence = overview.split("。", 1)[0].strip()
        if first_sentence:
            return trim_text(first_sentence, 80)

    tags = Counter(tag for item in items for tag in item.get("topic_tags", []) or item.get("tags", []))
    top_tags = {name for name, _ in tags.most_common(4)}
    if {"Agent", "企业应用"} & top_tags:
        return "今天更值得关注的不是单纯模型变强，而是 AI 继续进入真实工作流和企业场景。"
    if "开发者工具" in top_tags:
        return "今天的重点不在概念热度，而在开发工具和平台能力继续加速成熟。"
    return "今天的高价值信息更集中在可落地产品、研究进展与行业动作的交叉地带。"


def infer_reason_from_item(item: dict[str, Any]) -> str:
    source_type = str(item.get("source_type", "")).strip()
    category = str(item.get("display_section") or "").strip()
    title = clean_text(item.get("zh_title") or item.get("title"))
    if source_type in {"official_global", "official_china"}:
        return f"{title[:22]}来自一手官方来源，信息更完整，适合作为当天判断基准。"
    if source_type == "open_source":
        return "它更接近开发者可直接上手的能力变化，实操参考价值更高。"
    if category == "公司动态":
        return "它反映了公司层面的真实动作，比泛泛观点更能代表行业方向。"
    if category == "研究与趋势":
        return "它代表了近期技术演进或热点方向，适合判断接下来会往哪里走。"
    return "它对产品、技术或行业判断都有直接参考价值。"


def infer_audience_from_item(item: dict[str, Any]) -> str:
    section = str(item.get("display_section") or "").strip()
    source_type = str(item.get("source_type", "")).strip()
    if section == "产品与应用":
        return "产品经理、应用开发者、企业数字化团队"
    if section == "公司动态":
        return "行业研究者、投资人、战略和业务负责人"
    if section == "研究与趋势":
        return "算法工程师、模型团队、技术决策者"
    if source_type == "open_source":
        return "开发者、开源维护者、技术团队负责人"
    return "关注 AI 产品与行业变化的读者"


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def trim_text(text: str, limit: int) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    for separator in ("。", "，", "；", ".", ";", " "):
        idx = clipped.rfind(separator)
        if idx >= int(limit * 0.6):
            return clipped[:idx].strip("，；,; ")
    return clipped.rstrip("，；,; ") + "…"
