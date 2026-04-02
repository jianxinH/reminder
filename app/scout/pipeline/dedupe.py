from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    unique_items: list[dict[str, Any]] = []

    for item in items:
        url = str(item.get("url", "")).strip()
        content_hash = str(item.get("content_hash", "")).strip()

        if url and url in seen_urls:
            continue
        if content_hash and content_hash in seen_hashes:
            continue

        merged = False
        for index, existing in enumerate(unique_items):
            if is_same_topic(existing, item):
                unique_items[index] = merge_same_topic(existing, item)
                merged = True
                break
        if merged:
            continue

        if url:
            seen_urls.add(url)
        if content_hash:
            seen_hashes.add(content_hash)
        unique_items.append({**item, "related_sources": item.get("related_sources", [])})

    return unique_items


def is_same_topic(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_title = title_signature(left.get("title", ""))
    right_title = title_signature(right.get("title", ""))
    if not left_title or not right_title:
        return False

    similarity = SequenceMatcher(None, left_title, right_title).ratio()
    if similarity >= 0.92:
        return True

    shared_tokens = set(left_title.split()) & set(right_title.split())
    if len(shared_tokens) >= 5 and dates_close(left.get("published_at", ""), right.get("published_at", "")):
        return True
    return False


def merge_same_topic(primary: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    related_sources = list(primary.get("related_sources", []))
    related_sources.append(
        {
            "source": candidate.get("source", ""),
            "url": candidate.get("url", ""),
            "title": candidate.get("title", ""),
        }
    )

    primary_score = score_merge_candidate(primary)
    candidate_score = score_merge_candidate(candidate)
    winner = primary if primary_score >= candidate_score else candidate
    loser = candidate if winner is primary else primary
    merged = {**winner}
    merged["related_sources"] = dedupe_related_sources(
        list(winner.get("related_sources", []))
        + list(loser.get("related_sources", []))
        + related_sources
    )
    return merged


def score_merge_candidate(item: dict[str, Any]) -> tuple[int, int]:
    return (
        len(str(item.get("summary", ""))),
        len(str(item.get("title", ""))),
    )


def dedupe_related_sources(value: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in value:
        url = str(item.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result[:5]


def title_signature(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    stopwords = {"the", "a", "an", "of", "to", "and", "in", "for", "on", "with", "at", "by"}
    return " ".join(token for token in text.split() if token not in stopwords)


def dates_close(left: str, right: str) -> bool:
    left_dt = parse_datetime(left)
    right_dt = parse_datetime(right)
    if left_dt is None or right_dt is None:
        return False
    return abs((left_dt - right_dt).total_seconds()) <= 3 * 24 * 3600


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
