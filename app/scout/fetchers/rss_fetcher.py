from __future__ import annotations

from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from app.scout.fetchers.http_client import fetch_text
from app.scout.fetchers.generic_list_fetcher import fetch_html_list_items
from app.scout.fetchers.source_registry import load_sources
from app.scout.utils.logger import get_logger

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
logger = get_logger(__name__)


def fetch_all_rss_items(sources_file: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for source in load_sources(sources_file):
        try:
            source_items = fetch_source_items(source)
        except Exception as exc:
            logger.warning("跳过来源 %s: %s", source.get("name", source.get("url", "unknown")), exc)
            continue
        items.extend(source_items)
    return items


def fetch_source_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    strategy = source.get("fetch_strategy", "rss")
    if strategy == "rss":
        return fetch_rss_items(source)
    if strategy == "html_list":
        return fetch_html_list_items(source)
    raise ValueError(f"Unsupported fetch strategy: {strategy}")


def fetch_rss_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    xml_text = fetch_text(
        source["url"],
        timeout=20.0,
        referer=source.get("referer", ""),
    )
    root = ET.fromstring(xml_text)
    if root.tag.endswith("feed"):
        return parse_atom_feed(root, source)
    return parse_rss_feed(root, source)


def parse_rss_feed(root: ET.Element, source: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    channel = root.find("channel")
    if channel is None:
        return items

    for entry in channel.findall("item"):
        link = get_text(entry.find("link"))
        title = get_text(entry.find("title"))
        if not link or not title:
            continue
        items.append(
            build_item(
                source,
                title=title,
                url=link.strip(),
                published_at=normalize_date(get_text(entry.find("pubDate"))),
                summary=get_text(entry.find("description")),
                category_hint=get_text(entry.find("category")) or source.get("category_hint", ""),
            )
        )
    return items


def parse_atom_feed(root: ET.Element, source: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = get_text(entry.find("atom:title", ATOM_NS))
        link = ""
        for candidate in entry.findall("atom:link", ATOM_NS):
            href = candidate.attrib.get("href", "").strip()
            rel = candidate.attrib.get("rel", "alternate")
            if href and rel in {"alternate", ""}:
                link = href
                break
        if not title or not link:
            continue
        items.append(
            build_item(
                source,
                title=title,
                url=link,
                published_at=normalize_date(
                    get_text(entry.find("atom:updated", ATOM_NS))
                    or get_text(entry.find("atom:published", ATOM_NS))
                ),
                summary=get_text(entry.find("atom:summary", ATOM_NS))
                or get_text(entry.find("atom:content", ATOM_NS)),
                category_hint=first_atom_category(entry) or source.get("category_hint", ""),
            )
        )
    return items


def build_item(
    source: dict[str, Any],
    *,
    title: str,
    url: str,
    published_at: str,
    summary: str,
    category_hint: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "url": url,
        "source": source.get("name") or hostname_from_url(url),
        "source_type": source.get("source_type", "media"),
        "published_at": published_at,
        "summary": summary,
        "category_hint": category_hint,
        "priority": int(source.get("priority", 50)),
        "raw_category": category_hint,
    }


def first_atom_category(entry: ET.Element) -> str:
    category = entry.find("atom:category", ATOM_NS)
    if category is None:
        return ""
    return category.attrib.get("term", "").strip()


def get_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def hostname_from_url(url: str) -> str:
    return urlparse(url).netloc


def normalize_date(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value.strip()
