from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from app.scout.fetchers.http_client import fetch_text


def fetch_html_list_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    text = fetch_text(
        source["url"],
        timeout=25.0,
        referer=source.get("referer", ""),
    )

    parser = source.get("parser", "")
    if parser == "product_hunt":
        return parse_product_hunt(text, source)
    if parser == "github_trending":
        return parse_github_trending(text, source)
    if parser == "github_explore":
        return parse_github_explore(text, source)
    if parser == "github_topic":
        return parse_github_topic(text, source)
    if parser == "arxiv_list":
        return parse_arxiv_list(text, source)
    if parser == "deepmind_blog":
        return parse_generic_articles(text, source, include_patterns=["/discover/blog/"])
    if parser == "deepmind_publications":
        return parse_generic_articles(text, source, include_patterns=["/research/publications/"])
    if parser == "anthropic_news":
        return parse_generic_articles(text, source, include_patterns=["/news/"])
    if parser == "anthropic_research":
        return parse_generic_articles(text, source, include_patterns=["/research/"])
    if parser == "huggingface_papers":
        return parse_huggingface_papers(text, source)
    if parser == "papers_with_code":
        return parse_papers_with_code(text, source)
    if parser == "techcrunch_ai":
        return parse_generic_articles(text, source, include_patterns=["/20"])
    if parser == "venturebeat_ai":
        return parse_generic_articles(text, source, include_patterns=["/20", "/ai/"])
    return parse_generic_articles(text, source, include_patterns=[])


def parse_generic_articles(html_text: str, source: dict[str, Any], include_patterns: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_text, flags=re.I | re.S):
        href = normalize_url(match.group(1), source["url"])
        title = clean_html_text(match.group(2))
        if not href or not title or len(title) < 12:
            continue
        if include_patterns and not any(pattern in href for pattern in include_patterns):
            continue
        if hostname(href) != hostname(source["url"]):
            continue
        if href in seen:
            continue
        seen.add(href)
        surrounding = html_text[max(0, match.start() - 500): match.end() + 1000]
        items.append(
            build_item(
                source,
                title=title,
                url=href,
                published_at=extract_datetime(surrounding),
                summary=extract_paragraph(surrounding),
            )
        )
        if len(items) >= 20:
            break
    return items


def parse_product_hunt(html_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a[^>]+href="(/posts/[^"#?]+)"[^>]*>(.*?)</a>', html_text, flags=re.I | re.S):
        href = normalize_url(match.group(1), source["url"])
        title = clean_html_text(match.group(2))
        if not title or len(title) < 3 or href in seen:
            continue
        seen.add(href)
        surrounding = html_text[max(0, match.start() - 400): match.end() + 800]
        items.append(
            build_item(
                source,
                title=title,
                url=href,
                published_at=extract_datetime(surrounding),
                summary=extract_paragraph(surrounding),
            )
        )
        if len(items) >= 15:
            break
    return items


def parse_github_trending(html_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = re.compile(r'<h2[^>]*>\s*<a[^>]+href="(/[^"/\s]+/[^"/\s]+)"[^>]*>(.*?)</a>', re.I | re.S)
    for match in pattern.finditer(html_text):
        href = normalize_url(match.group(1), source["url"])
        title = clean_html_text(match.group(2)).replace(" / ", "/")
        if href in seen:
            continue
        seen.add(href)
        surrounding = html_text[max(0, match.start() - 300): match.end() + 1000]
        items.append(
            build_item(
                source,
                title=title,
                url=href,
                published_at="",
                summary=extract_paragraph(surrounding),
            )
        )
        if len(items) >= 20:
            break
    return items


def parse_github_explore(html_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    return parse_github_topic(html_text, source)


def parse_github_topic(html_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a[^>]+href="(/[^"/\s]+/[^"/\s]+)"[^>]*>(.*?)</a>', html_text, flags=re.I | re.S):
        href = normalize_url(match.group(1), source["url"])
        if "/topics/" in href or hostname(href) != "github.com":
            continue
        title = clean_html_text(match.group(2)).replace(" / ", "/")
        if len(title) < 3 or href in seen:
            continue
        surrounding = html_text[max(0, match.start() - 300): match.end() + 900]
        summary = extract_paragraph(surrounding)
        if not summary:
            continue
        seen.add(href)
        items.append(build_item(source, title=title, url=href, published_at="", summary=summary))
        if len(items) >= 20:
            break
    return items


def parse_arxiv_list(html_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<dt>.*?<a href="(/abs/[^"]+)".*?</dt>\s*<dd>(.*?)</dd>',
        re.I | re.S,
    )
    for match in pattern.finditer(html_text):
        href = normalize_url(match.group(1), source["url"])
        block = match.group(2)
        title_match = re.search(r'Title:\s*</span>\s*(.*?)\s*</div>', block, re.I | re.S)
        title = clean_html_text(title_match.group(1)) if title_match else ""
        summary_match = re.search(r'<p class="mathjax">(.*?)</p>', block, re.I | re.S)
        summary = clean_html_text(summary_match.group(1)) if summary_match else ""
        if not title:
            continue
        items.append(build_item(source, title=title, url=href, published_at="", summary=summary))
        if len(items) >= 25:
            break
    return items


def parse_huggingface_papers(html_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a[^>]+href="(/papers/\d+\.\d+)"[^>]*>(.*?)</a>', html_text, flags=re.I | re.S):
        href = normalize_url(match.group(1), source["url"])
        title = clean_html_text(match.group(2))
        if not title or href in seen:
            continue
        seen.add(href)
        surrounding = html_text[max(0, match.start() - 300): match.end() + 900]
        items.append(
            build_item(
                source,
                title=title,
                url=href,
                published_at=extract_datetime(surrounding),
                summary=extract_paragraph(surrounding),
            )
        )
        if len(items) >= 20:
            break
    return items


def parse_papers_with_code(html_text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    return parse_generic_articles(html_text, source, include_patterns=["/paper/"])


def build_item(
    source: dict[str, Any],
    *,
    title: str,
    url: str,
    published_at: str,
    summary: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "url": url,
        "source": source.get("name") or hostname(url),
        "source_type": source.get("source_type", "media"),
        "published_at": published_at,
        "summary": summary,
        "category_hint": source.get("category_hint", ""),
        "priority": int(source.get("priority", 50)),
    }


def extract_datetime(text: str) -> str:
    patterns = [
        r'datetime="([^"]+)"',
        r'time datetime="([^"]+)"',
        r'content="(\d{4}-\d{2}-\d{2}T[^"]+)"',
        r'(\d{4}-\d{2}-\d{2})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1).strip()
    return ""


def extract_paragraph(text: str) -> str:
    paragraph_patterns = [
        r'<p[^>]*>(.*?)</p>',
        r'<span[^>]*>(.*?)</span>',
        r'<div[^>]*class="[^"]*(?:description|summary|excerpt)[^"]*"[^>]*>(.*?)</div>',
    ]
    for pattern in paragraph_patterns:
        for match in re.finditer(pattern, text, flags=re.I | re.S):
            cleaned = clean_html_text(match.group(1))
            if len(cleaned) >= 24:
                return cleaned[:280]
    return ""


def clean_html_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_url(url: str, base_url: str) -> str:
    if not url:
        return ""
    return urljoin(base_url, html.unescape(url.strip()))


def hostname(url: str) -> str:
    return urlparse(url).netloc
