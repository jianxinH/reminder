from __future__ import annotations

import json
from typing import Any

import httpx

from app.scout.utils.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """
你是一名中文 AI 科技日报编辑，写作风格接近科技公众号主编，而不是研究报告撰写人。你的任务不只是做摘要，还要完成筛选、归类、提炼重点和编辑式表达。

你的目标不是机械复述原文，而是帮助读者快速判断：
1. 这件事发生了什么？
2. 为什么值得关注？
3. 对哪些人有价值？
4. 它在今天的 AI 资讯里重要性如何？

写作要求：
- 中文表达自然、清楚，像公众号编辑写给读者看的资讯导语
- “发生了什么”必须写成适合日报正文展示的完整中文摘要，优先使用 2~4 句完整句子
- 优先说人话，少用公文和行业报告腔
- 可以有编辑判断，但不要夸张，不要编造原文没有的信息
- 输出必须是合法 JSON
- 不要输出 markdown
- 不要输出额外解释
""".strip()

USER_PROMPT_TEMPLATE = """
请将以下资讯整理成适合“每日 AI 资讯日报”的信息卡片，并严格输出 JSON。

【输入内容】
标题: {title}
来源: {source}
发布时间: {published_at}
链接: {url}
原始摘要: {summary}

【任务要求】
1. 判断是否属于 AI 相关资讯
2. 判断分类：
   - 新闻
   - 产品
   - 应用
   - 开源
   - 融资/公司动态
   - 研究
   - 其他
3. 输出一个适合中文日报展示的标题
4. 给出一句话结论
5. 说明“发生了什么”，写成完整摘要段落
6. 说明“为什么重要”
7. 说明“谁应该关注”
8. 给出一句不超过 80 字的编辑短评
9. 判断是否建议收录到日报
10. 给出 0~100 的重要性分数

【JSON 输出格式】
{{
  "is_ai_related": true,
  "category_suggestion": "产品",
  "zh_title": "这里填写中文标题",
  "one_line_takeaway": "这里填写一句话结论",
  "what_happened": "这里填写适合日报正文展示的完整摘要，尽量 2~4 句，句子完整，不要只写半句。",
  "why_it_matters": "这里填写为什么重要。",
  "who_should_care": "这里填写谁应该关注。",
  "my_commentary": "这里填写编辑短评。",
  "include_in_report": true,
  "importance_score": 88,
  "confidence": 0.91,
  "tags": ["AI产品", "Agent", "开发者工具"]
}}

注意：
- 必须输出合法 JSON
- 不要加代码块
- 不要加解释
- 不要照抄标题作为摘要
- “what_happened”必须是完整摘要段落
""".strip()


class NewsSummarizer:
    def __init__(self, api_key: str, model: str, language: str = "zh-CN", base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.language = language
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    def summarize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        fallback = self.fallback_summary(item)
        if not self.api_key:
            return fallback

        try:
            response = self._request_model(item)
            response.raise_for_status()
            payload = response.json()
            parsed = self._normalize_payload(self._parse_model_json(payload), item, fallback)
            return parsed
        except Exception as exc:
            logger.warning("单条资讯卡片生成失败，已回退到本地兜底: %s", exc)
            return fallback

    def _request_model(self, item: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self._uses_chat_completions():
            return httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": self._build_user_prompt(item)},
                    ],
                    "temperature": 0.2,
                },
                timeout=45.0,
            )
        return httpx.post(
            f"{self.base_url}/responses",
            headers=headers,
            json={
                "model": self.model,
                "input": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_user_prompt(item)},
                ],
                "text": {"format": {"type": "json_object"}},
            },
            timeout=45.0,
        )

    def fallback_summary(self, item: dict[str, Any], reason: str = "信息不足") -> dict[str, Any]:
        summary = clean_sentence(item.get("summary") or item.get("title", ""))
        detected_category = normalize_category(item.get("category") or item.get("raw_category") or "其他")
        is_ai_related = is_probably_ai_related(item)
        importance = estimate_importance(item, is_ai_related=is_ai_related)
        include_in_report = is_ai_related and importance >= 40
        takeaway = summary[:90] if summary else reason
        detail = clean_paragraph(
            item.get("summary") or f"{item.get('title', '')} 目前公开信息有限，但从标题和来源判断，仍与当天 AI 产业、产品或研究动态相关。",
            220,
        )
        commentary = clean_paragraph(
            item.get("summary") or f"这条内容更适合作为当天判断链路里的补充信息，帮助理解 {item.get('source', '相关来源')} 在持续关注什么。",
            140,
        )

        return {
            "is_ai_related": is_ai_related,
            "category_suggestion": detected_category,
            "zh_title": item.get("title", "")[:120],
            "one_line_takeaway": takeaway or "信息不足",
            "what_happened": detail,
            "why_it_matters": commentary,
            "who_should_care": "",
            "my_commentary": commentary,
            "include_in_report": include_in_report,
            "importance_score": importance,
            "confidence": 0.35 if is_ai_related else 0.2,
            "tags": infer_tags(item, detected_category),
            "short_summary": takeaway or "信息不足",
            "model_name": "",
            "generated_by_model": False,
            "related_sources": item.get("related_sources", []),
        }

    def _build_user_prompt(self, item: dict[str, Any]) -> str:
        return USER_PROMPT_TEMPLATE.format(
            title=item.get("title", ""),
            source=item.get("source", ""),
            published_at=item.get("published_at", ""),
            url=item.get("url", ""),
            summary=item.get("summary", ""),
        )

    def _uses_chat_completions(self) -> bool:
        return "modelscope" in self.base_url.lower()

    def _parse_response_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return json.loads(extract_json_text(output_text))

        for output in payload.get("output", []):
            for content in output.get("content", []):
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return json.loads(extract_json_text(text))
        return {}

    def _parse_chat_completions_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        for choice in payload.get("choices", []):
            message = choice.get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return json.loads(extract_json_text(content))
            if isinstance(content, list):
                for part in content:
                    text = part.get("text") if isinstance(part, dict) else None
                    if isinstance(text, str) and text.strip():
                        return json.loads(extract_json_text(text))
        return {}

    def _parse_model_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._uses_chat_completions():
            return self._parse_chat_completions_json(payload)
        return self._parse_response_json(payload)

    def _normalize_payload(
        self,
        parsed: dict[str, Any],
        item: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if not parsed:
            return fallback

        is_ai_related = bool(parsed.get("is_ai_related", fallback["is_ai_related"]))
        category = normalize_category(parsed.get("category_suggestion") or fallback["category_suggestion"])
        importance = clamp_score(parsed.get("importance_score", fallback["importance_score"]))
        include_in_report = bool(parsed.get("include_in_report", importance >= 55 and is_ai_related))

        normalized = {
            "is_ai_related": is_ai_related,
            "category_suggestion": category,
            "zh_title": clean_sentence(parsed.get("zh_title") or fallback["zh_title"])[:120] or fallback["zh_title"],
            "one_line_takeaway": clean_sentence(parsed.get("one_line_takeaway") or fallback["one_line_takeaway"])[:120],
            "what_happened": clean_paragraph(parsed.get("what_happened") or fallback["what_happened"], 420),
            "why_it_matters": clean_paragraph(parsed.get("why_it_matters") or fallback["why_it_matters"], 240),
            "who_should_care": clean_sentence(parsed.get("who_should_care") or fallback["who_should_care"])[:120],
            "my_commentary": clean_paragraph(parsed.get("my_commentary") or fallback["my_commentary"], 140),
            "include_in_report": include_in_report,
            "importance_score": importance,
            "confidence": clamp_confidence(parsed.get("confidence", fallback["confidence"])),
            "tags": normalize_tags(parsed.get("tags"), item, category),
            "short_summary": clean_sentence(parsed.get("one_line_takeaway") or fallback["one_line_takeaway"])[:120],
            "model_name": self.model,
            "generated_by_model": True,
            "related_sources": item.get("related_sources", []),
        }

        if not normalized["is_ai_related"]:
            normalized["include_in_report"] = False
            normalized["importance_score"] = min(normalized["importance_score"], 35)
        return normalized


def clamp_score(value: Any) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        score = 50
    return max(0, min(score, 100))


def clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.0
    return max(0.0, min(confidence, 1.0))


def normalize_category(value: str) -> str:
    raw = (value or "").strip()
    mapping = {
        "模型": "研究",
        "产品": "产品",
        "应用": "应用",
        "开源": "开源",
        "融资": "融资/公司动态",
        "公司动态": "融资/公司动态",
        "融资/公司动态": "融资/公司动态",
        "研究": "研究",
        "新闻": "新闻",
        "其他": "其他",
    }
    lowered = raw.lower()
    english_mapping = {
        "news": "新闻",
        "product": "产品",
        "products": "产品",
        "application": "应用",
        "app": "应用",
        "open source": "开源",
        "opensource": "开源",
        "open-source": "开源",
        "funding": "融资/公司动态",
        "company": "融资/公司动态",
        "research": "研究",
        "other": "其他",
    }
    return mapping.get(raw) or english_mapping.get(lowered) or "其他"


def normalize_tags(value: Any, item: dict[str, Any], category: str) -> list[str]:
    if isinstance(value, list):
        tags = [clean_sentence(str(tag)) for tag in value if str(tag).strip()]
    elif isinstance(value, str):
        tags = [clean_sentence(part) for part in value.split(",") if part.strip()]
    else:
        tags = []

    normalized = []
    seen: set[str] = set()
    for tag in tags + infer_tags(item, category):
        if not tag:
            continue
        if tag not in seen:
            normalized.append(tag[:24])
            seen.add(tag)
    return normalized[:6]


def infer_tags(item: dict[str, Any], category: str) -> list[str]:
    text = " ".join(
        [
            str(item.get("title", "")),
            str(item.get("summary", "")),
            str(item.get("source", "")),
        ]
    ).lower()
    tags: list[str] = []
    keyword_map = {
        "Agent": ["agent"],
        "开发者工具": ["api", "sdk", "developer", "copilot", "cli"],
        "大模型": ["gpt", "llm", "model", "claude", "gemini", "qwen"],
        "开源": ["open source", "github", "apache", "weights"],
        "企业应用": ["enterprise", "workflow", "automation"],
        "多模态": ["multimodal", "video", "image", "voice", "audio"],
    }
    for tag, keywords in keyword_map.items():
        if any(keyword in text for keyword in keywords):
            tags.append(tag)
    if category == "产品":
        tags.append("AI产品")
    if category == "应用":
        tags.append("AI应用")
    if category == "研究":
        tags.append("AI研究")
    return tags[:5]


def is_probably_ai_related(item: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(item.get("title", "")),
            str(item.get("summary", "")),
            str(item.get("source", "")),
            str(item.get("category", "")),
        ]
    ).lower()
    ai_keywords = [
        "ai",
        "artificial intelligence",
        "machine learning",
        "model",
        "llm",
        "gpt",
        "agent",
        "copilot",
        "openai",
        "anthropic",
        "deepmind",
        "hugging face",
        "qwen",
        "gemini",
        "claude",
        "智能",
        "大模型",
        "模型",
        "生成式",
        "人工智能",
        "机器学习",
    ]
    return any(keyword in text for keyword in ai_keywords)


def estimate_importance(item: dict[str, Any], is_ai_related: bool) -> int:
    text = " ".join([str(item.get("title", "")), str(item.get("summary", ""))]).lower()
    score = 25 if is_ai_related else 10

    high_signal = ["launch", "released", "release", "introduces", "announced", "open source", "api", "funding"]
    medium_signal = ["update", "benchmark", "research", "agent", "tool", "platform", "feature"]
    low_signal = ["opinion", "commentary", "thoughts"]

    score += sum(12 for keyword in high_signal if keyword in text)
    score += sum(6 for keyword in medium_signal if keyword in text)
    score -= sum(8 for keyword in low_signal if keyword in text)
    score += source_type_bonus(item.get("source_type", ""))
    score += source_language_bonus(item.get("source_language", ""))

    if len(clean_sentence(item.get("summary", ""))) >= 120:
        score += 8
    if item.get("related_sources"):
        score += 6
    return max(0, min(score, 95))


def source_type_bonus(source_type: str) -> int:
    mapping = {
        "official_global": 18,
        "official_china": 16,
        "product_discovery": 8,
        "open_source": 12,
        "research": 14,
        "media_global": 6,
        "media_china": 4,
        "official": 14,
        "product": 8,
        "media": 5,
    }
    return mapping.get(str(source_type or "").strip(), 0)


def source_language_bonus(source_language: str) -> int:
    language = str(source_language or "").strip().lower()
    if language == "zh":
        return 2
    if language == "en":
        return 1
    return 0


def clean_sentence(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def clean_paragraph(value: Any, limit: int) -> str:
    text = clean_sentence(value)
    if not text:
        return "信息不足"
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    for separator in ("。", "！", "？", ".", ";", "；"):
        last_index = clipped.rfind(separator)
        if last_index >= int(limit * 0.6):
            return clipped[: last_index + 1].strip()
    return clipped.rstrip(" ,，。！？；") + "…"


def extract_json_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end >= start:
        return stripped[start : end + 1]
    return stripped
