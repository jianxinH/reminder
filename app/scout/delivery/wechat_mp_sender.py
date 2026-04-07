from __future__ import annotations

import html
import re
from pathlib import Path

import httpx


LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def send_report_to_wechat_mp(
    *,
    report_path: str,
    app_id: str,
    app_secret: str,
    author: str,
    thumb_media_id: str,
    digest: str = "",
    content_source_url: str = "",
    base_url: str = "https://api.weixin.qq.com",
) -> dict:
    if not app_id or not app_secret:
        raise RuntimeError("WeChat MP draft send failed: missing app credentials")
    if not thumb_media_id:
        raise RuntimeError("WeChat MP draft send failed: missing thumb_media_id")

    article = build_wechat_mp_article(
        report_path=report_path,
        author=author,
        thumb_media_id=thumb_media_id,
        digest=digest,
        content_source_url=content_source_url,
    )
    access_token = get_access_token(app_id=app_id, app_secret=app_secret, base_url=base_url)
    response = httpx.post(
        f"{base_url}/cgi-bin/draft/add",
        params={"access_token": access_token},
        json={"articles": [article]},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errcode") not in (None, 0):
        raise RuntimeError(f"WeChat MP draft send failed: {payload}")
    return payload


def upload_wechat_mp_thumb(
    *,
    image_path: str,
    app_id: str,
    app_secret: str,
    base_url: str = "https://api.weixin.qq.com",
) -> dict:
    if not app_id or not app_secret:
        raise RuntimeError("WeChat MP thumb upload failed: missing app credentials")

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Thumb image not found: {path}")

    access_token = get_access_token(app_id=app_id, app_secret=app_secret, base_url=base_url)
    with path.open("rb") as file_obj:
        response = httpx.post(
            f"{base_url}/cgi-bin/material/add_material",
            params={"access_token": access_token, "type": "image"},
            files={"media": (path.name, file_obj, guess_content_type(path))},
            timeout=30.0,
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errcode") not in (None, 0) and "media_id" not in payload:
        raise RuntimeError(f"WeChat MP thumb upload failed: {payload}")
    return payload


def get_access_token(*, app_id: str, app_secret: str, base_url: str) -> str:
    response = httpx.get(
        f"{base_url}/cgi-bin/token",
        params={
            "grant_type": "client_credential",
            "appid": app_id,
            "secret": app_secret,
        },
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if "access_token" not in payload:
        raise RuntimeError(f"WeChat MP token failed: {payload}")
    return payload["access_token"]


def build_wechat_mp_article(
    *,
    report_path: str,
    author: str,
    thumb_media_id: str,
    digest: str = "",
    content_source_url: str = "",
) -> dict:
    path = Path(report_path)
    if not path.exists():
        raise FileNotFoundError(f"Report not found: {path}")

    markdown = path.read_text(encoding="utf-8")
    title = extract_title(markdown, fallback=path.stem)
    html_content = markdown_to_wechat_html(markdown)
    article_digest = digest.strip() or extract_digest(markdown)

    return {
        "title": title,
        "author": author.strip() or "AI Daily Scout",
        "digest": article_digest,
        "content": html_content,
        "content_source_url": content_source_url.strip(),
        "thumb_media_id": thumb_media_id.strip(),
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
        "show_cover_pic": 1,
    }


def extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def extract_digest(markdown: str) -> str:
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    body_lines = [line for line in lines if not line.startswith("#") and not line.startswith(">")]
    digest = " ".join(body_lines[:3]).strip()
    return digest[:120]


def markdown_to_wechat_html(markdown: str) -> str:
    html_lines: list[str] = []
    in_list = False
    in_blockquote = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    def close_blockquote() -> None:
        nonlocal in_blockquote
        if in_blockquote:
            html_lines.append("</blockquote>")
            in_blockquote = False

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            close_list()
            close_blockquote()
            continue

        if stripped.startswith("> "):
            close_list()
            if not in_blockquote:
                html_lines.append('<blockquote style="margin:16px 0;padding:12px 16px;background:#f7f8fa;border-left:4px solid #d0d7de;color:#4b5563;">')
                in_blockquote = True
            html_lines.append(f"<p>{format_inline(stripped[2:].strip())}</p>")
            continue

        close_blockquote()

        if stripped.startswith("- "):
            if not in_list:
                html_lines.append('<ul style="padding-left:22px;margin:12px 0;">')
                in_list = True
            html_lines.append(f"<li>{format_inline(stripped[2:].strip())}</li>")
            continue

        close_list()

        if stripped.startswith("### "):
            html_lines.append(f'<h3 style="font-size:18px;line-height:1.6;margin:22px 0 10px;font-weight:700;">{format_inline(stripped[4:].strip())}</h3>')
        elif stripped.startswith("## "):
            html_lines.append(f'<h2 style="font-size:22px;line-height:1.6;margin:28px 0 12px;font-weight:700;">{format_inline(stripped[3:].strip())}</h2>')
        elif stripped.startswith("# "):
            html_lines.append(f'<h1 style="font-size:28px;line-height:1.5;margin:0 0 18px;font-weight:800;">{format_inline(stripped[2:].strip())}</h1>')
        else:
            html_lines.append(f'<p style="font-size:15px;line-height:1.9;margin:10px 0;color:#111827;">{format_inline(stripped)}</p>')

    close_list()
    close_blockquote()
    return "\n".join(html_lines)


def format_inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = LINK_RE.sub(lambda match: f'<a href="{html.escape(match.group(2), quote=True)}">{html.escape(match.group(1), quote=False)}</a>', escaped)
    return escaped


def guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"
