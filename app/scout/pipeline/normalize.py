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
    "36氪 AI",
    "机器之心",
    "新智元",
}

DENYLIST_KEYWORDS = {
    "giveaway",
    "casino",
    "airdrop",
    "lottery",
    "dating",
    "porn",
    "betting",
    "เครดิตฟรี",
}


def normalize_items(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    discovered_date = datetime.now(timezone.utc).date().isoformat()

    for item in raw_items:
        url = str(item.get("url", "")).strip()
        canonical_url = canonicalize_url(url)
        raw_title = str(item.get("title", "") or "")
        clean_title = clean_title_text(raw_title, fallback_summary=str(item.get("summary", "") or ""))
        if not canonical_url or not clean_title:
            continue

        summary = clean_summary(item.get("summary", ""))
        source = clean_text(item.get("source", ""))
        raw_category = clean_text(item.get("raw_category", "") or item.get("category_hint", ""))
        published_at = str(item.get("published_at", "")).strip()
        source_type = clean_text(item.get("source_type", ""))
        source_language = clean_text(item.get("source_language", ""))
        category_hint = clean_text(item.get("category_hint", ""))
        priority = normalize_priority(item.get("priority", 50))
        normalized_title = title_signature(clean_title)

        normalized_item = {
            "title": clean_title,
            "clean_title": clean_title,
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
            "summary": summary,
            "summary_zh": "",
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

    if len(title) < 6:
        return False
    if not summary:
        return False
    if any(keyword in haystack for keyword in DENYLIST_KEYWORDS):
        return False
    if "github.com" in url and not looks_like_ai_github_item(title, summary):
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


def clean_summary(value: Any) -> str:
    text = clean_text(value)
    text = text.replace("\u200b", "").strip(" -|")
    return text[:400]


def clean_title_text(value: Any, *, fallback_summary: str = "") -> str:
    text = clean_text(value)
    text = text.replace("\u200b", "")
    text = DATE_PREFIX_RE.sub("", text)
    text = NOISY_TITLE_PREFIX_RE.sub("", text)
    text = TITLE_SEPARATOR_RE.split(text)[0].strip() if len(text) > 140 else text
    text = re.sub(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b\.?,?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip(" -|:：,，")

    if len(text) > 160 or looks_polluted_title(text):
        fallback = first_sentence(clean_text(fallback_summary))
        if fallback and 8 <= len(fallback) <= 100:
            text = fallback
        else:
            text = text[:120].strip(" -|:：,，")
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
    match = re.split(r"(?<=[。！？.!?])\s+", text, maxsplit=1)
    return match[0].strip()


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
