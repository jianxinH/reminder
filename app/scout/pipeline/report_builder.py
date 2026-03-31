from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def build_daily_report(items: list[dict], top_n: int, timezone_name: str) -> str:
    tz = ZoneInfo(timezone_name)
    report_date = datetime.now(tz).date().isoformat()
    selected_items = sorted(
        items,
        key=lambda item: item.get("importance_score", 50),
        reverse=True,
    )[:top_n]

    lines = [
        f"# AI Daily Scout 日报 - {report_date}",
        "",
        f"- 生成时区：`{timezone_name}`",
        f"- 收录条数：`{len(selected_items)}`",
        "",
    ]

    if not selected_items:
        lines.extend(
            [
                "## 今日概览",
                "",
                "今天没有抓取到可收录的新内容。",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(["## 今日概览", ""])
    for index, item in enumerate(selected_items, start=1):
        category = item.get("category_suggestion") or item.get("category") or "其他"
        lines.extend(
            [
                f"### {index}. {item.get('zh_title') or item.get('title')}",
                "",
                f"- 分类：`{category}`",
                f"- 来源：`{item.get('source', '')}`",
                f"- 发布时间：`{item.get('published_at', '') or '未知'}`",
                f"- 重要性：`{item.get('importance_score', 50)}`",
                f"- 摘要：{item.get('short_summary', '')}",
                f"- 值得关注：{item.get('why_it_matters', '')}",
                f"- 链接：[原文]({item.get('url', '')})",
                "",
            ]
        )

    return "\n".join(lines)
