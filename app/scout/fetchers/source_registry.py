from __future__ import annotations

from typing import Any

import yaml


SOURCE_GROUPS = (
    "official_global",
    "official_china",
    "product_discovery",
    "open_source",
    "research_sources",
    "media_global",
    "media_china",
)


def load_sources(sources_file: str) -> list[dict[str, Any]]:
    with open(sources_file, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    sources: list[dict[str, Any]] = []
    for group_name in SOURCE_GROUPS:
        for source in data.get(group_name, []):
            if not source.get("enabled", False):
                continue
            sources.append(
                {
                    "group": group_name,
                    "name": source.get("name", ""),
                    "url": source.get("url", ""),
                    "enabled": bool(source.get("enabled", False)),
                    "source_type": source.get("source_type", infer_source_type(group_name)),
                    "fetch_strategy": source.get("fetch_strategy", "rss"),
                    "parser": source.get("parser", ""),
                    "referer": source.get("referer", ""),
                    "source_language": source.get("source_language", infer_source_language(group_name)),
                    "category_hint": source.get("category_hint", ""),
                    "priority": int(source.get("priority", 50)),
                }
            )
    return sources


def infer_source_type(group_name: str) -> str:
    mapping = {
        "official_global": "official_global",
        "official_china": "official_china",
        "product_discovery": "product_discovery",
        "open_source": "open_source",
        "research_sources": "research",
        "media_global": "media_global",
        "media_china": "media_china",
    }
    return mapping.get(group_name, "media_global")


def infer_source_language(group_name: str) -> str:
    chinese_groups = {"official_china", "media_china"}
    return "zh" if group_name in chinese_groups else "en"
