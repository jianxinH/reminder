from __future__ import annotations

import hashlib
import re
from typing import Any


def normalize_items(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in raw_items:
        url = str(item.get("url", "")).strip()
        title = clean_text(item.get("title", ""))
        if not url or not title:
            continue

        summary = clean_text(item.get("summary", ""))
        source = clean_text(item.get("source", ""))
        raw_category = clean_text(item.get("raw_category", ""))
        published_at = str(item.get("published_at", "")).strip()

        normalized.append(
            {
                "title": title,
                "url": url,
                "source": source,
                "published_at": published_at,
                "summary": summary,
                "raw_category": raw_category,
                "content_hash": build_content_hash(title, summary, source),
            }
        )
    return normalized


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_content_hash(title: str, summary: str, source: str) -> str:
    payload = f"{title}\n{summary}\n{source}".strip().lower()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
