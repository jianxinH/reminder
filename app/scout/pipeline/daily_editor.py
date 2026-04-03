from __future__ import annotations

import json
from collections import Counter
from typing import Any

import httpx

from app.scout.utils.logger import get_logger

logger = get_logger(__name__)

DAILY_EDITOR_PROMPT = """
你是一名 AI 科技日报主编。下面是今天已经筛选后的资讯卡片列表。

请输出一份日报级总结，严格返回 JSON，包含：
1. overview: 用2~3句话总结今天AI资讯的整体情况
2. top_stories: 列出今天最值得关注的3件事，每件事给一句原因
3. trend_observations: 给出2~4条今日趋势观察
4. follow_up_topics: 给出2~3个值得明天继续追踪的话题
5. low_priority_summary: 用1段话概括那些重要性较低但可备案的信息

要求：
- 信息密度高
- 不空泛
- 不重复单条卡片原话
- 不编造未提供的信息
- 必须返回合法 JSON
""".strip()


class DailyEditor:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    def build_daily_summary(
        self,
        items: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        fallback = self._fallback_summary(items, stats)
        if not items or not self.api_key:
            return fallback

        try:
            response = httpx.post(
                f"{self.base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": [
                        {"role": "system", "content": DAILY_EDITOR_PROMPT},
                        {"role": "user", "content": self._build_items_prompt(items, stats)},
                    ],
                    "text": {"format": {"type": "json_object"}},
                },
                timeout=45.0,
            )
            response.raise_for_status()
            payload = response.json()
            parsed = self._parse_response_json(payload)
            return self._normalize_summary(parsed, fallback)
        except Exception as exc:
            logger.warning("日报级总结生成失败，已回退到本地兜底: %s", exc)
            return fallback

    def _build_items_prompt(self, items: list[dict[str, Any]], stats: dict[str, Any]) -> str:
        compact_items = [
            {
                "title": item.get("zh_title") or item.get("title"),
                "category": item.get("category_suggestion") or item.get("category"),
                "takeaway": item.get("one_line_takeaway"),
                "why_it_matters": item.get("why_it_matters"),
                "importance_score": item.get("importance_score"),
                "tags": item.get("tags", []),
                "source": item.get("source"),
            }
            for item in items[:20]
        ]
        return json.dumps(
            {
                "stats": stats,
                "items": compact_items,
            },
            ensure_ascii=False,
        )

    def _parse_response_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return json.loads(output_text)
        for output in payload.get("output", []):
            for content in output.get("content", []):
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return json.loads(text)
        return {}

    def _normalize_summary(self, parsed: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        if not parsed:
            return fallback
        trend_items = filter_editorial_lines(
            normalize_string_list(parsed.get("trend_observations"), fallback["trend_observations"], 4),
            section="trend",
        )
        follow_up_items = filter_editorial_lines(
            normalize_string_list(parsed.get("follow_up_topics"), fallback["follow_up_topics"], 3),
            section="follow_up",
        )
        return {
            "overview": clean_text(parsed.get("overview")) or fallback["overview"],
            "top_stories": normalize_string_list(parsed.get("top_stories"), fallback["top_stories"], 3),
            "trend_observations": trend_items,
            "follow_up_topics": follow_up_items,
            "low_priority_summary": clean_text(parsed.get("low_priority_summary")) or fallback["low_priority_summary"],
        }

    def _fallback_summary(self, items: list[dict[str, Any]], stats: dict[str, Any]) -> dict[str, Any]:
        categories = Counter(
            item.get("category_suggestion") or item.get("category") or "其他" for item in items
        )
        tags = Counter(tag for item in items for tag in item.get("tags", []))
        top_items = sorted(items, key=lambda item: item.get("importance_score", 0), reverse=True)[:3]
        low_priority_items = [item for item in items if item.get("importance_score", 0) < 60][:5]

        top_categories = "、".join(name for name, _ in categories.most_common(3)) or "产品、应用与研究"
        top_tags = "、".join(name for name, _ in tags.most_common(4)) or "AI产品、开发者工具、模型能力"

        overview = (
            f"今天 AI 资讯整体仍以{top_categories}为主，说明市场关注点继续集中在可落地产品、开发工具和模型能力变化。"
            f"高频关键词包括{top_tags}，从中可以看出行业仍在围绕“更好用、更可部署、更贴近业务”推进。"
        )

        top_stories = [
            f"{item.get('zh_title') or item.get('title')}：重要性分数 {item.get('importance_score', 0)}，适合进入今日重点。"
            for item in top_items
        ] or ["今天暂无明显高优先级头条，建议以栏目速览为主。"]

        trend_observations = [
            f"{name}类内容占比较高，说明今天的信息流更偏向这一方向。"
            for name, _ in categories.most_common(3)
        ]

        follow_up_topics = [
            f"继续跟踪与“{tag}”相关的后续发布和产品更新。"
            for tag, _ in tags.most_common(3)
        ]

        low_priority_summary = (
            "低优先级资讯主要是信息量较少、更新幅度有限或偏补充性质的动态，仍建议保留做背景跟踪。"
        )
        if low_priority_items:
            low_priority_summary = (
                "低优先级简讯主要包括："
                + "；".join((item.get("zh_title") or item.get("title") or "未命名资讯")[:40] for item in low_priority_items)
                + "。它们信息量相对有限，但可作为后续观察的背景信号。"
            )

        return {
            "overview": overview,
            "top_stories": top_stories[:3],
            "trend_observations": filter_editorial_lines(trend_observations[:4], section="trend"),
            "follow_up_topics": filter_editorial_lines(follow_up_topics[:3], section="follow_up"),
            "low_priority_summary": low_priority_summary,
        }


def normalize_string_list(value: Any, fallback: list[str], limit: int) -> list[str]:
    if isinstance(value, list):
        cleaned = [clean_text(item) for item in value if clean_text(item)]
        return cleaned[:limit] or fallback[:limit]
    if isinstance(value, str) and clean_text(value):
        return [clean_text(value)][:limit]
    return fallback[:limit]


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def filter_editorial_lines(lines: list[str], *, section: str) -> list[str]:
    filtered: list[str] = []
    seen: set[str] = set()
    generic_markers = {
        "trend": [
            "内容占比较高，说明今天的信息流更偏向这一方向",
            "资讯分布较分散",
        ],
        "follow_up": [
            "继续跟踪与",
            "后续发布和产品更新",
            "继续观察主要厂商",
        ],
    }

    for raw_line in lines:
        line = clean_text(raw_line)
        if not line or line in seen:
            continue
        if any(marker in line for marker in generic_markers.get(section, [])):
            continue
        seen.add(line)
        filtered.append(line)
    return filtered
