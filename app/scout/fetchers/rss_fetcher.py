from __future__ import annotations

from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx
import yaml

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def load_sources(sources_file: str) -> list[dict[str, Any]]:
    with open(sources_file, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    sources = data.get("sources", [])
    return [source for source in sources if source.get("enabled", False)]


def fetch_all_rss_items(sources_file: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for source in load_sources(sources_file):
        items.extend(fetch_rss_items(source))
    return items


def fetch_rss_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    response = httpx.get(source["url"], timeout=20.0, follow_redirects=True)
    response.raise_for_status()

    root = ET.fromstring(response.text)
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
            {
                "title": title,
                "url": link.strip(),
                "source": source.get("name") or hostname_from_url(link),
                "published_at": normalize_date(get_text(entry.find("pubDate"))),
                "summary": get_text(entry.find("description")),
                "raw_category": get_text(entry.find("category")),
            }
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
            {
                "title": title,
                "url": link,
                "source": source.get("name") or hostname_from_url(link),
                "published_at": normalize_date(
                    get_text(entry.find("atom:updated", ATOM_NS))
                    or get_text(entry.find("atom:published", ATOM_NS))
                ),
                "summary": get_text(entry.find("atom:summary", ATOM_NS))
                or get_text(entry.find("atom:content", ATOM_NS)),
                "raw_category": first_atom_category(entry),
            }
        )
    return items


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
