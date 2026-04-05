from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from typing import Any


SOFT_DEDUPE_THRESHOLD = 0.88


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_canonical_urls: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()
    seen_source_titles: set[tuple[str, str]] = set()
    unique_items: list[dict[str, Any]] = []

    for item in items:
        canonical_url = str(item.get("canonical_url") or item.get("url") or "").strip()
        normalized_title = str(item.get("normalized_title") or title_signature(item.get("title", ""))).strip()
        source = str(item.get("source", "")).strip().lower()

        if canonical_url and canonical_url in seen_canonical_urls:
            continue
        if normalized_title and ("*", normalized_title) in seen_titles:
            continue
        if source and normalized_title and (source, normalized_title) in seen_source_titles:
            continue

        merged = False
        for index, existing in enumerate(unique_items):
            if is_same_topic(existing, item):
                unique_items[index] = merge_same_topic(existing, item)
                merged = True
                break
        if merged:
            continue

        if canonical_url:
            seen_canonical_urls.add(canonical_url)
        if normalized_title:
            seen_titles.add(("*", normalized_title))
        if source and normalized_title:
            seen_source_titles.add((source, normalized_title))
        unique_items.append(
            {
                **item,
                "related_sources": dedupe_related_sources(item.get("related_sources", [])),
                "related_links": dedupe_related_sources(item.get("related_links", [])),
            }
        )

    return unique_items


def is_same_topic(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_title = str(left.get("normalized_title") or title_signature(left.get("title", ""))).strip()
    right_title = str(right.get("normalized_title") or title_signature(right.get("title", ""))).strip()
    if not left_title or not right_title:
        return False

    title_similarity = SequenceMatcher(None, left_title, right_title).ratio()
    if title_similarity >= 0.94:
        return True

    left_text = f"{left_title} {title_signature(left.get('summary', ''))}".strip()
    right_text = f"{right_title} {title_signature(right.get('summary', ''))}".strip()
    text_similarity = SequenceMatcher(None, left_text, right_text).ratio()
    if text_similarity >= SOFT_DEDUPE_THRESHOLD and dates_close(left.get("published_at", ""), right.get("published_at", "")):
        return True

    shared_tokens = set(left_title.split()) & set(right_title.split())
    return len(shared_tokens) >= 5 and dates_close(left.get("published_at", ""), right.get("published_at", ""))


def merge_same_topic(primary: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    primary_score = score_merge_candidate(primary)
    candidate_score = score_merge_candidate(candidate)
    winner = primary if primary_score >= candidate_score else candidate
    loser = candidate if winner is primary else primary

    merged = {**winner}
    merged["related_sources"] = dedupe_related_sources(
        list(winner.get("related_sources", []))
        + list(loser.get("related_sources", []))
        + [link_entry(loser)]
    )
    merged["related_links"] = dedupe_related_sources(
        list(winner.get("related_links", []))
        + list(loser.get("related_links", []))
        + [link_entry(loser)]
    )
    merged["cluster_id"] = merged.get("cluster_id") or stable_cluster_id(winner)
    return merged


def score_merge_candidate(item: dict[str, Any]) -> tuple[int, int, int, int]:
    authority = {
        "official_global": 5,
        "official_china": 5,
        "research": 4,
        "open_source": 4,
        "media_global": 3,
        "media_china": 2,
        "product_discovery": 2,
    }.get(str(item.get("source_type", "")).strip(), 1)
    summary_len = len(str(item.get("summary", "")))
    title_len = len(str(item.get("title", "")))
    has_published_at = 1 if item.get("published_at") else 0
    return (authority, summary_len, has_published_at, title_len)


def dedupe_related_sources(value: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in value:
        url = str(item.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(
            {
                "source": str(item.get("source", "")).strip(),
                "url": url,
                "title": str(item.get("title", "")).strip(),
            }
        )
    return result[:6]


def link_entry(item: dict[str, Any]) -> dict[str, str]:
    return {
        "source": str(item.get("source", "")).strip(),
        "url": str(item.get("url", "")).strip(),
        "title": str(item.get("title", "")).strip(),
    }


def stable_cluster_id(item: dict[str, Any]) -> str:
    basis = str(item.get("normalized_title") or item.get("canonical_url") or item.get("url") or "").strip()
    return basis[:64]


def title_signature(value: str) -> str:
    text = str(value or "").lower()
    filtered = "".join(ch if ch.isalnum() or "\u4e00" <= ch <= "\u9fff" else " " for ch in text)
    return " ".join(filtered.split())


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
