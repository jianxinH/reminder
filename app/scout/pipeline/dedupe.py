from __future__ import annotations


def dedupe_items(items: list[dict]) -> list[dict]:
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    unique_items: list[dict] = []

    for item in items:
        url = str(item.get("url", "")).strip()
        content_hash = str(item.get("content_hash", "")).strip()

        if url and url in seen_urls:
            continue
        if content_hash and content_hash in seen_hashes:
            continue

        if url:
            seen_urls.add(url)
        if content_hash:
            seen_hashes.add(content_hash)
        unique_items.append(item)

    return unique_items
