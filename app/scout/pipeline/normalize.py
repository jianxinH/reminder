from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DATE_PREFIX_RE = re.compile(
    r"^\s*(?:[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s+"
)
NOISY_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?:Announcements?|Economic Research|News|Blog|Research|Press Release|Update|Latest)\s*[:\-|]\s*",
    re.IGNORECASE,
)
MULTISPACE_RE = re.compile(r"\s+")
TITLE_SEPARATOR_RE = re.compile(r"\s+(?:\||｜|—|-)\s+")
ORG_KEYWORDS = (
    "university",
    "institute",
    "center",
    "centre",
    "school",
    "department",
    "laboratory",
    "lab",
    "college",
    "academy",
    "kaust",
)
BAD_SUMMARY_ENDINGS = (
    "with",
    "for",
    "to",
    "and",
    "or",
    "that",
    "which",
    "using",
    "based on",
    "built for",
    "designed to",
    "through",
    "that enhances",
    "that goes beyond",
)
ALLOWLIST_SOURCES = {
    "OpenAI News",
    "Anthropic News",
    "Anthropic Research",
    "Google DeepMind Blog",
    "Google DeepMind Publications",
    "Hugging Face Blog",
    "Hugging Face Papers",
    "Hugging Face Trending Papers",
    "GitHub Trending",
    "GitHub Explore",
    "GitHub Topics: ai",
    "GitHub Topics: llm",
    "GitHub Topics: ai-agents",
    "arXiv cs.AI recent",
    "arXiv cs.AI new",
    "arXiv cs.CL recent",
    "arXiv cs.LG recent",
    "TechCrunch AI",
    "36kr AI",
    "机器之心",
    "新智元",
}


def normalize_items(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    discovered_date = datetime.now(timezone.utc).date().isoformat()

    for item in raw_items:
        url = str(item.get("url", "")).strip()
        canonical_url = canonicalize_url(url)
        raw_title = clean_text(item.get("title", ""))
        raw_summary = pick_best_raw_summary(item)
        clean_title = clean_title_text(raw_title, fallback_summary=raw_summary)
        if not canonical_url or not clean_title:
            continue

        summary = build_usable_summary(raw_summary, clean_title)
        if not summary:
            continue

        source = clean_text(item.get("source", ""))
        raw_category = clean_text(item.get("raw_category", "") or item.get("category_hint", ""))
        published_at = str(item.get("published_at", "")).strip()
        source_type = clean_text(item.get("source_type", ""))
        source_language = clean_text(item.get("source_language", ""))
        category_hint = clean_text(item.get("category_hint", ""))
        priority = normalize_priority(item.get("priority", 50))
        normalized_title = title_signature(clean_title)
        summary_quality = summary_quality_check(summary, clean_title)

        normalized_item = {
            "raw_title": raw_title,
            "title": clean_title,
            "clean_title": clean_title,
            "display_title": build_display_title(clean_title, raw_summary, canonical_url),
            "normalized_title": normalized_title,
            "url": url,
            "canonical_url": canonical_url,
            "source": source,
            "source_name": source,
            "source_type": source_type,
            "source_language": source_language,
            "published_at": published_at,
            "published_date": published_at[:10] if published_at else "",
            "discovered_date": discovered_date,
            "raw_summary": raw_summary,
            "summary": summary,
            "summary_zh": summary,
            "summary_quality": summary_quality,
            "raw_category": raw_category,
            "category_hint": category_hint,
            "priority": priority,
            "display_section": "",
            "trend_type": "",
            "topic_tags": [],
            "quality_score": 0,
            "editorial_score": 0,
            "cluster_id": "",
            "related_links": [],
            "why_it_matters_zh": "",
            "why_template_id": "",
            "is_trend_note_shown": False,
            "content_hash": build_content_hash(clean_title, summary, source),
        }
        if should_keep_item(normalized_item):
            normalized.append(normalized_item)
    return normalized


def should_keep_item(item: dict[str, Any]) -> bool:
    title = str(item.get("title", "")).strip()
    summary = str(item.get("summary", "")).strip()
    source = str(item.get("source", "")).strip()
    source_type = str(item.get("source_type", "")).strip()
    url = str(item.get("canonical_url", "")).strip().lower()
    haystack = f"{title} {summary} {url}".lower()

    if len(title) < 5:
        return False
    if not summary:
        return False
    if looks_like_affiliation(summary):
        return False
    if source in ALLOWLIST_SOURCES:
        return True
    if source_type in {"official_global", "official_china", "open_source", "research", "media_global", "media_china"}:
        return True
    return looks_ai_related(title, summary, source)


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = MULTISPACE_RE.sub(" ", text)
    return text.strip()


def clean_title_text(value: str, *, fallback_summary: str = "") -> str:
    text = clean_text(value)
    text = DATE_PREFIX_RE.sub("", text)
    text = NOISY_TITLE_PREFIX_RE.sub("", text)
    if len(text) > 140:
        text = TITLE_SEPARATOR_RE.split(text)[0].strip()
    text = re.sub(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b\.?,?\s*", "", text, flags=re.IGNORECASE)
    text = text.strip(" -|:：,，")
    if len(text) > 160 or looks_polluted_title(text):
        fallback = first_sentence(clean_text(fallback_summary))
        if fallback and 8 <= len(fallback) <= 100:
            text = fallback
        else:
            text = text[:120].strip(" -|:：,，")
    return text


def build_usable_summary(raw_summary: str, title: str) -> str:
    summary = clean_text(raw_summary)
    if not summary or looks_like_affiliation(summary):
        return fallback_summary_from_title(title)
    quality = summary_quality_check(summary, title)
    if quality >= 70:
        return trim_text(summary, 220)
    extracted = first_sentence(summary)
    if summary_quality_check(extracted, title) >= 70:
        return trim_text(extracted, 220)
    rewritten = rewrite_summary_fallback(title, summary)
    if rewritten:
        return rewritten
    return fallback_summary_from_title(title)


def pick_best_raw_summary(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    candidates = [
        item.get("summary", ""),
        item.get("description", ""),
        item.get("content", ""),
        item.get("subtitle", ""),
        metadata.get("description", "") if isinstance(metadata, dict) else "",
        metadata.get("summary", "") if isinstance(metadata, dict) else "",
    ]
    best = ""
    best_score = -1
    title = clean_text(item.get("title", ""))
    for candidate in candidates:
        text = clean_text(candidate)
        if not text:
            continue
        score = summary_quality_check(text, title)
        if score > best_score:
            best = text
            best_score = score
    return best


def summary_quality_check(summary: str, title: str) -> int:
    text = clean_text(summary)
    if not text:
        return 0
    score = 100
    if len(text) < 24:
        score -= 45
    if looks_like_affiliation(text):
        score -= 70
    if not ends_like_complete_sentence(text):
        score -= 25
    if is_title_like_summary(text, title):
        score -= 20
    return max(0, min(score, 100))


def looks_like_affiliation(text: str) -> bool:
    cleaned = clean_text(text)
    lowered = cleaned.lower()
    if not cleaned:
        return False
    words = cleaned.split()
    upper_ratio = sum(1 for part in words if part.isupper() and len(part) > 1) / max(len(words), 1)
    has_org_keyword = any(keyword in lowered for keyword in ORG_KEYWORDS)
    has_verb = any(token in lowered for token in (" is ", " are ", " was ", " were ", "build", "launch", "release", "introduce", "develop", "improve"))
    return (has_org_keyword and not has_verb) or (len(words) <= 8 and has_org_keyword) or upper_ratio >= 0.45


def ends_like_complete_sentence(text: str) -> bool:
    cleaned = clean_text(text)
    if not cleaned:
        return False
    if cleaned.endswith(("。", "！", "？", ".", "!", "?")):
        return True
    lowered = cleaned.lower()
    return not any(lowered.endswith(ending) for ending in BAD_SUMMARY_ENDINGS)


def is_title_like_summary(summary: str, title: str) -> bool:
    return title_signature(summary) == title_signature(title)


def rewrite_summary_fallback(title: str, summary: str) -> str:
    title_lower = title.lower()
    if "agent" in title_lower:
        return f"该项目聚焦 AI Agent 方向，适合关注智能体工作流与应用落地的读者。"
    if any(keyword in title_lower for keyword in ("framework", "sdk", "toolkit", "cli", "copilot")):
        return f"该项目聚焦开发工具与工程集成，适合关注 AI 应用构建效率的读者。"
    if any(keyword in title_lower for keyword in ("benchmark", "evaluation", "paper", "rag", "multimodal")):
        return f"该内容聚焦模型能力或方法进展，适合关注研究趋势与技术方向的读者。"
    return fallback_summary_from_title(title)


def fallback_summary_from_title(title: str) -> str:
    return f"该项目聚焦 {title[:28]} 相关方向，适合关注 AI 产品与技术进展的读者。"


def build_display_title(clean_title: str, summary: str, canonical_url: str) -> str:
    if "github.com/" in canonical_url.lower():
        path = urlsplit(canonical_url).path.strip("/")
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2:
            repo_name = prettify_repo_name(parts[1])
            desc = extract_repo_short_desc(summary)
            if desc:
                return f"{repo_name}：{desc}"
            return repo_name
    return clean_title


def prettify_repo_name(repo_name: str) -> str:
    pretty = repo_name.replace("-", " ").replace("_", " ").strip()
    return " ".join(part.capitalize() if part.islower() else part for part in pretty.split())


def extract_repo_short_desc(summary: str) -> str:
    text = clean_text(summary)
    if not text:
        return ""
    text = first_sentence(text)
    text = trim_text(text, 28)
    return text


def looks_polluted_title(text: str) -> bool:
    lower = text.lower()
    if len(text) > 120:
        return True
    pollution_markers = ["we've made", "read more", "click here", "subscribe", "newsletter", "announcements"]
    return any(marker in lower for marker in pollution_markers)


def first_sentence(text: str) -> str:
    if not text:
        return ""
    parts = re.split(r"(?<=[。！？.!?])\s+", text, maxsplit=1)
    return parts[0].strip()


def trim_text(text: str, limit: int) -> str:
    cleaned = clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit]
    for sep in ("。", "，", "；", ".", ";", " "):
        idx = clipped.rfind(sep)
        if idx >= int(limit * 0.6):
            return clipped[:idx].strip("，；,; ")
    return clipped.rstrip("，；,; ") + "…"


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    query_items = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    query = urlencode(query_items)
    return urlunsplit((scheme, netloc, path, query, ""))


def build_content_hash(title: str, summary: str, source: str) -> str:
    payload = f"{title}\n{summary}\n{source}".strip().lower()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def title_signature(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    text = MULTISPACE_RE.sub(" ", text).strip()
    stopwords = {"the", "a", "an", "of", "to", "and", "in", "for", "on", "with", "at", "by"}
    return " ".join(token for token in text.split() if token not in stopwords)


def normalize_priority(value: Any) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError):
        priority = 50
    return max(0, min(priority, 100))


def looks_ai_related(title: str, summary: str, source: str) -> bool:
    text = f"{title} {summary} {source}".lower()
    keywords = [
        "ai",
        "agent",
        "model",
        "llm",
        "gpt",
        "claude",
        "gemini",
        "qwen",
        "deepmind",
        "openai",
        "anthropic",
        "hugging face",
        "人工智能",
        "大模型",
        "智能体",
        "机器学习",
        "多模态",
    ]
    return any(keyword in text for keyword in keywords)


def looks_like_ai_github_item(title: str, summary: str) -> bool:
    return looks_ai_related(title, summary, "github")
