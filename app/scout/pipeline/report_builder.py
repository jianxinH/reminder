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
    report_date = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    regular_items = [item for section in SECTION_ORDER for item in section_items.get(section, [])]
    all_items = top_items + regular_items + low_priority_items
    trend_state = {"shown": 0, "report_date": report_date}
    reason_state: Counter[str] = Counter()

    lines = [
        f"# AI Daily Scout｜{report_date}",
        "",
        FIXED_INTRO,
        "",
        "## 今日概览",
        "",
    ]
    lines.extend(build_overview_lines(stats, editorial_summary, all_items))
    lines.extend(["", f"## {build_top_heading(len(top_items))}", ""])

    if top_items:
        for index, item in enumerate(top_items, start=1):
            lines.extend(render_top_item(index, item, trend_state, reason_state))
    else:
        lines.extend(["### 暂无重点条目", "今天没有足够高质量的内容进入重点推荐。", ""])

    for section in SECTION_ORDER:
        items = section_items.get(section, [])
        if not items:
            continue
        lines.extend([f"## {section}", ""])
        for item in items:
            lines.extend(render_section_item(item, reason_state))

    if low_priority_items:
        lines.extend(["## 快讯速览", ""])
        for item in low_priority_items[:8]:
            lines.append(f"- **{get_display_title(item)}**：{build_quick_hint(item)} [原文]({item.get('url') or ''})")
        lines.append("")

    lines.extend(["## 今天怎么读", ""])
    lines.extend(generate_reading_guide(all_items, section_items))
    lines.extend(["", "## 备注", ""])
    lines.extend(build_notes(all_items, trend_state))
    return "\n".join(lines).strip() + "\n"


def build_overview_lines(stats: dict[str, Any], editorial_summary: dict[str, Any], items: list[dict[str, Any]]) -> list[str]:
    raw_count = int(stats.get("raw_count") or stats.get("fetched_count") or 0)
    final_count = int(stats.get("final_count") or stats.get("included_count") or 0)
    topic_counter = Counter(tag for item in items for tag in item.get("topic_tags", []) or [])
    main_topics = "、".join(topic_name(tag) for tag, _ in topic_counter.most_common(4))
    if not main_topics:
        main_topics = "Agent、企业级 AI、开发工具、多模态"

    lines: list[str] = []
    if raw_count > 0 and 0 <= final_count <= raw_count:
        lines.append(f"- 今日共抓取 AI 相关资讯 **{raw_count}** 条，经去重、聚类与质量筛选后，最终收录 **{final_count}** 条。")
    elif final_count > 0:
        lines.append(f"- 今日共收录 **{final_count}** 条资讯，抓取链路统计异常，已按最终可用内容生成日报。")
    else:
        lines.append("- 今日抓取链路统计异常，以下内容按当前可用资讯生成。")
    lines.append(f"- 今日关注主线：{main_topics}")
    lines.append(f"- 编辑判断：{choose_editorial_judgment(editorial_summary, items)}")
    return lines


def build_top_heading(count: int) -> str:
    if count <= 0:
        return "今日最值得看的内容"
    if count == 1:
        return "今日最值得看的一件事"
    return f"今日最值得看的 {count} 件事"


def render_top_item(index: int, item: dict[str, Any], trend_state: dict[str, Any], reason_state: Counter[str]) -> list[str]:
    lines = [
        f"### {index}）{get_display_title(item)}",
        build_one_line_summary(item),
        "",
        f"**核心内容：** {build_story_body(item, limit=220)}",
        f"**为什么值得看：** {build_reason_to_watch(item, reason_state)}",
        f"**技术/产品看点：** {build_extended_takeaway(item)}",
        f"**适合谁看：** {build_target_audience(item)}",
    ]
    trend_note = build_trend_note(item, trend_state, section="top")
    if trend_note:
        lines.append(trend_note)
    lines.extend([f"**原文：** {item.get('url') or ''}", ""])
    return lines


def render_section_item(item: dict[str, Any], reason_state: Counter[str]) -> list[str]:
    return [
        f"### {get_display_title(item)}",
        build_one_line_summary(item),
        "",
        f"**核心内容：** {build_story_body(item, limit=180)}",
        f"**看点：** {build_extended_takeaway(item)}",
        f"**为什么值得关注：** {build_reason_to_watch(item, reason_state)}",
        f"**原文：** {item.get('url') or ''}",
        "",
    ]


def get_display_title(item: dict[str, Any]) -> str:
    return (
        str(item.get("display_title") or "").strip()
        or str(item.get("clean_title") or "").strip()
        or str(item.get("zh_title") or "").strip()
        or str(item.get("title") or "").strip()
        or "未命名条目"
    )


def build_one_line_summary(item: dict[str, Any]) -> str:
    summary = (
        item.get("one_line_takeaway")
        or item.get("summary_zh")
        or item.get("short_summary")
        or item.get("summary")
        or item.get("what_happened")
        or ""
    )
    text = clean_text(summary)
    if not text:
        return f"该条目聚焦 {get_display_title(item)} 相关方向，适合关注 AI 产品、工程和研究进展的读者。"
    return trim_text(text, 80)


def build_story_body(item: dict[str, Any], *, limit: int) -> str:
    candidates = [
        item.get("what_happened"),
        item.get("summary_zh"),
        item.get("summary"),
        item.get("short_summary"),
        item.get("one_line_takeaway"),
    ]
    for candidate in candidates:
        text = clean_text(candidate)
        if len(text) >= 40:
            return trim_text(text, limit)
    fallback = clean_text(item.get("one_line_takeaway") or item.get("summary") or "")
    if fallback:
        return trim_text(fallback, min(limit, 120))
    return f"{get_display_title(item)} 目前公开信息有限，但仍值得作为今天的补充阅读线索。"


def build_reason_to_watch(item: dict[str, Any], reason_state: Counter[str]) -> str:
    provided = clean_text(item.get("why_it_matters_zh") or item.get("why_it_matters"))
    if provided and provided != get_display_title(item):
        return trim_text(provided, 110)

    tags = {str(tag).lower() for tag in item.get("topic_tags", []) or []}
    if {"agent", "tooling", "coding"} & tags:
        return choose_reason(
            "tooling",
            [
                "它更接近开发者能直接上手的工程能力变化，适合拿来判断工作流集成、工具替换和团队效率提升的现实价值。",
                "这类条目通常不只是功能更新，更能反映 Agent 与开发工具链正在如何进入真实生产流程。",
            ],
            reason_state,
        )
    if {"funding", "company", "pricing"} & tags:
        return choose_reason(
            "company",
            [
                "它释放的是商业化与行业节奏信号，能帮助判断资金、合作和产品路线是否正在向更成熟的企业场景收拢。",
                "相比单点产品更新，这类公司级动作更适合放进长期观察框架里看，因为它往往预示着下一阶段的市场重心。",
            ],
            reason_state,
        )
    if {"paper", "benchmark"} & tags:
        return choose_reason(
            "research",
            [
                "它更适合用来判断近期研究重心和方法演进，对做模型、算法评估和技术选型的人有持续参考价值。",
                "这类内容的价值不在一时热度，而在于它往往能提前暴露下一轮方法趋势和评测方向。",
            ],
            reason_state,
        )
    if {"multimodal"} & tags:
        return choose_reason(
            "multimodal",
            [
                "它体现的是能力边界和应用场景的外扩，适合判断多模态能力何时真正从展示走向稳定可用。",
                "如果你关注视频、视觉和语音的落地空间，这类条目通常比单一指标更有长期观察意义。",
            ],
            reason_state,
        )

    section = str(item.get("display_section") or "")
    if section == "产品与应用":
        return choose_reason(
            "product",
            [
                "这条信息更贴近真实使用场景，适合产品、应用和平台团队快速判断是否值得跟进、试用或接入。",
                "它反映的不是概念层面的热闹，而是可落地能力是否正在进入更可执行的状态。",
            ],
            reason_state,
        )
    if section == "公司动态":
        return choose_reason(
            "company_section",
            [
                "它对应的是公司层面的真实动作，更适合拿来判断行业资源流向、合作格局和下一步战略重心。",
                "如果你更关心市场和商业进展，这类信息通常比短期产品热度更值得持续追踪。",
            ],
            reason_state,
        )
    return choose_reason(
        "generic",
        [
            "它补上了今天判断链路里缺少的一块背景信息，适合作为继续追踪某个方向的起点。",
            "虽然它未必是当天最热的一条，但对理解今天信息结构和趋势拼图仍有明显帮助。",
        ],
        reason_state,
    )


def build_extended_takeaway(item: dict[str, Any]) -> str:
    candidates = [
        item.get("my_commentary"),
        item.get("why_it_matters_zh"),
        item.get("why_it_matters"),
        item.get("what_happened"),
    ]
    for candidate in candidates:
        text = clean_text(candidate)
        if len(text) >= 28:
            return trim_text(text, 150)

    tags = {str(tag).lower() for tag in item.get("topic_tags", []) or []}
    if {"agent", "tooling", "coding"} & tags:
        return "从工程角度看，这类进展通常对应更具体的接入方式、协作边界和开发工作流变化，适合评估是否值得纳入团队工具栈。"
    if {"paper", "benchmark"} & tags:
        return "从研究角度看，这类内容更值得关注方法假设、评测口径和可复用思路，而不只是结论本身。"
    if {"funding", "company", "pricing"} & tags:
        return "从商业角度看，它更像是行业节奏信号，能帮助判断产品路线、资源投入与企业化推进是否正在提速。"
    return "这条内容更适合作为理解今天 AI 行业进展的一块背景拼图，重点不在单点热度，而在它能补充什么判断依据。"


def choose_reason(template_id: str, options: list[str], reason_state: Counter[str]) -> str:
    index = reason_state[template_id]
    reason_state[template_id] += 1
    if index < len(options):
        return options[index]
    return options[-1]


def build_target_audience(item: dict[str, Any]) -> str:
    audience = item.get("target_audience_zh") or item.get("who_should_care")
    if isinstance(audience, list):
        text = "、".join(str(part).strip() for part in audience if str(part).strip())
    else:
        text = clean_text(audience)
    if text:
        return trim_text(text, 60)
    section = str(item.get("display_section") or "")
    if section == "产品与应用":
        return "产品经理、应用开发者、AI 平台与业务集成团队"
    if section == "公司动态":
        return "行业研究者、管理层、投资与战略团队"
    return "算法工程师、模型团队、技术决策者"


def build_quick_hint(item: dict[str, Any]) -> str:
    hint = item.get("one_line_takeaway") or item.get("summary_zh") or item.get("summary") or ""
    text = clean_text(hint)
    if not text:
        return "可作补充阅读"
    return trim_text(text, 32)


def build_trend_note(item: dict[str, Any], trend_state: dict[str, Any], *, section: str) -> str:
    trend_type = str(item.get("trend_type", "")).strip()
    published_date = str(item.get("published_date", "")).strip()
    report_date = str(trend_state.get("report_date", "")).strip()
    if trend_type != "trending" or not published_date or published_date == report_date:
        return ""
    if section != "top" or trend_state["shown"] >= 2:
        return ""
    trend_state["shown"] += 1
    return "注：该内容为当日趋势上升，并非当日首次发布。"


def choose_editorial_judgment(editorial_summary: dict[str, Any], items: list[dict[str, Any]]) -> str:
    overview = clean_text(editorial_summary.get("overview"))
    if overview and len(overview) >= 24:
        return trim_text(first_sentence(overview), 90)

    tags = Counter(tag for item in items for tag in item.get("topic_tags", []) or [])
    top_tags = {str(name).lower() for name, _ in tags.most_common(4)}
    if {"agent", "enterprise"} & top_tags:
        return "今天更值得关注的不是模型参数变化，而是 AI 正在继续进入真实工作流和企业场景。"
    if "tooling" in top_tags or "coding" in top_tags:
        return "今天的重点更偏工程侧，值得留意开发工具、框架和可落地能力的推进速度。"
    if {"paper", "benchmark"} & top_tags:
        return "今天整体偏研究向，更适合从方法、评测和趋势判断的角度阅读。"
    return "今天的高价值信息集中在可落地产品、研究进展与行业动作的交叉地带。"


def generate_reading_guide(all_items: list[dict[str, Any]], section_items: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    topic_counter = Counter(tag for item in all_items for tag in item.get("topic_tags", []) or [])
    section_counter = Counter(section for section, items in section_items.items() for _ in items)
    top_tags = [tag for tag, _ in topic_counter.most_common(3)]

    if "agent" in top_tags:
        lines.append("- 如果你关注 Agent，优先看 Top 重点和“产品与应用”里偏工作流、框架和工具链的条目。")
    if "tooling" in top_tags or section_counter.get("产品与应用", 0) >= section_counter.get("研究与趋势", 0):
        lines.append("- 今天偏应用与工程落地，建议先扫产品与应用，再回看值得纳入内部工具栈的项目。")
    if "paper" in top_tags or "benchmark" in top_tags or section_counter.get("研究与趋势", 0) >= 4:
        lines.append("- 今天研究向内容占比不低，如果你做模型、算法或评测，建议优先看“研究与趋势”。")
    if section_counter.get("公司动态", 0) >= 3:
        lines.append("- 如果你更关心行业信号，优先看“公司动态”里的融资、合作和战略动作。")
    if not lines:
        lines.append("- 建议先看 Top 重点，再按你的关注点选择产品、公司或研究栏目继续阅读。")
    return lines


def build_notes(all_items: list[dict[str, Any]], trend_state: dict[str, Any]) -> list[str]:
    notes = [
        "- 日报已对同主题内容做聚合，默认保留更原始、信息更完整的来源作为主条目。",
        "- 快讯速览仅保留可补充判断的条目，不再重复堆叠相同链接。",
    ]
    trending_old = [
        item
        for item in all_items
        if str(item.get("trend_type", "")).strip() == "trending"
        and str(item.get("published_date", "")).strip()
        and str(item.get("published_date", "")).strip() != str(trend_state.get("report_date", ""))
    ]
    if trending_old:
        notes.append("- 文中若出现“趋势上升”提示，表示该内容在当日热度明显走高，并不一定是当天首次发布。")
    return notes + [""]


def topic_name(tag: str) -> str:
    mapping = {
        "agent": "Agent",
        "enterprise": "企业级 AI",
        "tooling": "开发工具",
        "coding": "编程助手",
        "multimodal": "多模态",
        "paper": "论文",
        "benchmark": "评测",
        "model": "模型能力",
        "company": "公司动作",
        "funding": "融资与商业化",
    }
    return mapping.get(str(tag).lower(), str(tag))


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def first_sentence(text: str) -> str:
    cleaned = clean_text(text)
    for sep in ("。", "！", "？", ".", "!", "?"):
        idx = cleaned.find(sep)
        if idx != -1:
            return cleaned[: idx + 1].strip()
    return cleaned


def trim_text(text: str, limit: int) -> str:
    cleaned = clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit]
    for sep in ("。", "！", "？", ".", ";", " "):
        idx = clipped.rfind(sep)
        if idx >= int(limit * 0.6):
            return clipped[: idx + 1].strip()
    return clipped.rstrip("，,;； ") + "…"
