from __future__ import annotations

import json
from typing import Any

import httpx

from app.scout.utils.logger import get_logger

logger = get_logger(__name__)


class NewsSummarizer:
    def __init__(self, api_key: str, model: str, language: str = "zh-CN") -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.language = language

    def summarize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        fallback = self.fallback_summary(item)
        if not self.api_key:
            return fallback

        try:
            prompt = self._build_prompt(item)
            response = httpx.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": prompt,
                    "text": {"format": {"type": "json_object"}},
                },
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()
            parsed = self._parse_response_json(payload)
            if not parsed:
                return fallback
            return {
                "zh_title": parsed.get("zh_title") or item.get("title", ""),
                "category_suggestion": parsed.get("category_suggestion") or item.get("category", "其他"),
                "short_summary": parsed.get("short_summary") or fallback["short_summary"],
                "why_it_matters": parsed.get("why_it_matters") or "值得持续关注。",
                "include_in_report": bool(parsed.get("include_in_report", True)),
                "importance_score": clamp_score(parsed.get("importance_score", 50)),
                "confidence": clamp_confidence(parsed.get("confidence", 0.0)),
                "tags": parsed.get("tags") or [],
                "model_name": self.model,
            }
        except Exception as exc:
            logger.warning("摘要生成失败，已回退原始摘要: %s", exc)
            return fallback

    def fallback_summary(self, item: dict[str, Any], reason: str = "模型摘要不可用，已回退为原始内容。") -> dict[str, Any]:
        return self._fallback_summary(item, reason)

    def _build_prompt(self, item: dict[str, Any]) -> str:
        return (
            f"请将下面的 AI 资讯整理为 {self.language} JSON。\n"
            "只返回一个 JSON 对象，字段必须包含："
            "zh_title, category_suggestion, short_summary, why_it_matters, "
            "include_in_report, importance_score, confidence, tags。\n"
            "importance_score 范围 0-100，confidence 范围 0-1，tags 为字符串数组。\n"
            f"标题: {item.get('title', '')}\n"
            f"来源: {item.get('source', '')}\n"
            f"发布时间: {item.get('published_at', '')}\n"
            f"已有分类: {item.get('category', '')}\n"
            f"摘要: {item.get('summary', '')}\n"
            f"链接: {item.get('url', '')}"
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

    def _fallback_summary(self, item: dict[str, Any], reason: str) -> dict[str, Any]:
        base_summary = item.get("summary") or item.get("title", "")
        return {
            "zh_title": item.get("title", ""),
            "category_suggestion": item.get("category", "其他"),
            "short_summary": base_summary[:200],
            "why_it_matters": reason,
            "include_in_report": True,
            "importance_score": 50,
            "confidence": 0.0,
            "tags": [],
            "model_name": self.model if self.api_key else "",
        }


def clamp_score(value: Any) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = 50
    return max(0, min(score, 100))


def clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.0
    return max(0.0, min(confidence, 1.0))
