from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path
from typing import Any

import httpx

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
STRONG_LABEL_RE = re.compile(r"^\*\*([^*]+?)：\*\*\s*(.+)$")


def send_report_to_wechat_mp(
    *,
    report_path: str,
    app_id: str,
    app_secret: str,
    author: str,
    thumb_media_id: str = "",
    digest: str = "",
    content_source_url: str = "",
    base_url: str = "https://api.weixin.qq.com",
    auto_generate_cover: bool = False,
    cover_image_api_key: str = "",
    cover_image_model: str = "gpt-image-1",
    cover_image_base_url: str = "https://api.openai.com/v1",
    cover_image_size: str = "1536x1024",
    cover_image_quality: str = "high",
) -> dict[str, Any]:
    if not app_id or not app_secret:
        raise RuntimeError("WeChat MP draft send failed: missing app credentials")

    article, meta = build_wechat_mp_article(
        report_path=report_path,
        author=author,
        thumb_media_id=thumb_media_id,
        digest=digest,
        content_source_url=content_source_url,
    )
    resolved_thumb_media_id = thumb_media_id.strip()
    generated_cover_path = ""
    if auto_generate_cover:
        generated_cover_path = generate_cover_image(
            report_path=report_path,
            prompt=meta["cover_prompt"],
            api_key=cover_image_api_key,
            model=cover_image_model,
            base_url=cover_image_base_url,
            size=cover_image_size,
            quality=cover_image_quality,
        )
        upload_payload = upload_wechat_mp_thumb(
            image_path=generated_cover_path,
            app_id=app_id,
            app_secret=app_secret,
            base_url=base_url,
        )
        resolved_thumb_media_id = str(upload_payload.get("media_id") or "").strip()
    if not resolved_thumb_media_id:
        raise RuntimeError("WeChat MP draft send failed: missing thumb_media_id")
    article["thumb_media_id"] = resolved_thumb_media_id

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
    meta_path = write_wechat_mp_meta(report_path=report_path, article=article, meta=meta)
    payload["local_meta_path"] = str(meta_path)
    payload["cover_prompt"] = meta["cover_prompt"]
    payload["thumb_media_id"] = resolved_thumb_media_id
    if generated_cover_path:
        payload["generated_cover_path"] = generated_cover_path
    return payload


def upload_wechat_mp_thumb(
    *,
    image_path: str,
    app_id: str,
    app_secret: str,
    base_url: str = "https://api.weixin.qq.com",
) -> dict[str, Any]:
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(report_path)
    if not path.exists():
        raise FileNotFoundError(f"Report not found: {path}")

    markdown = path.read_text(encoding="utf-8")
    title = extract_title(markdown, fallback=path.stem)
    cover_meta = build_cover_meta(markdown, title)
    html_content = markdown_to_wechat_html(markdown, cover_meta=cover_meta)
    article_digest = clamp_digest(digest.strip() or extract_digest(markdown))

    article = {
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
    return article, cover_meta


def generate_cover_image(
    *,
    report_path: str,
    prompt: str,
    api_key: str,
    model: str,
    base_url: str,
    size: str,
    quality: str,
) -> str:
    if not api_key.strip():
        raise RuntimeError("WeChat MP cover generation failed: missing cover image API key")

    normalized_base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
    response = httpx.post(
        f"{normalized_base_url}/images/generations",
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
        },
        timeout=90.0,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or []
    if not data:
        raise RuntimeError(f"WeChat MP cover generation failed: {payload}")

    target_path = Path(report_path).with_suffix(".cover.png")
    first = data[0]
    b64_json = first.get("b64_json")
    image_url = first.get("url")
    if isinstance(b64_json, str) and b64_json.strip():
        target_path.write_bytes(base64.b64decode(b64_json))
        return str(target_path)
    if isinstance(image_url, str) and image_url.strip():
        image_response = httpx.get(image_url, timeout=90.0)
        image_response.raise_for_status()
        target_path.write_bytes(image_response.content)
        return str(target_path)
    raise RuntimeError(f"WeChat MP cover generation failed: unsupported payload {payload}")


def write_wechat_mp_meta(*, report_path: str, article: dict[str, Any], meta: dict[str, Any]) -> Path:
    report = Path(report_path)
    target = report.with_suffix(report.suffix + ".wechat.json")
    payload = {
        "title": article.get("title", ""),
        "digest": article.get("digest", ""),
        "cover_title": meta.get("cover_title", ""),
        "cover_subtitle": meta.get("cover_subtitle", ""),
        "cover_keywords": meta.get("cover_keywords", []),
        "cover_prompt": meta.get("cover_prompt", ""),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def build_cover_meta(markdown: str, title: str) -> dict[str, Any]:
    sections = [line[3:].strip() for line in markdown.splitlines() if line.strip().startswith("## ")]
    top_keywords = [keyword for keyword in infer_cover_keywords(markdown)[:6]]
    cover_title = trim(title.replace("AI Daily Scout｜", "").strip(), 24) or "AI Daily Scout"
    cover_subtitle = "AI 产品 · 开源 · 研究 · 行业动态"
    prompt = (
        "为微信公众号 AI 日报生成封面图，风格参考科技媒体头图："
        "深色背景、青蓝霓虹、抽象数据流、立体光效、未来感、杂志封面构图。"
        f"主标题为“{cover_title}”，副标题为“{cover_subtitle}”。"
        f"核心关键词：{'、'.join(top_keywords) or 'AI日报、Agent、开发工具、多模态'}。"
        f"栏目线索：{'、'.join(sections[:4]) or '今日概览、重点推荐、产品与应用、研究与趋势'}。"
        "画面要适合公众号头图裁切，保持高级、克制、信息密度高。"
    )
    return {
        "cover_title": cover_title,
        "cover_subtitle": cover_subtitle,
        "cover_keywords": top_keywords,
        "cover_prompt": prompt,
    }


def infer_cover_keywords(markdown: str) -> list[str]:
    candidates: list[str] = []
    keyword_map = {
        "Agent": ("agent", "智能体"),
        "开发工具": ("tool", "sdk", "api", "copilot", "framework", "workflow"),
        "企业 AI": ("enterprise", "企业"),
        "多模态": ("multimodal", "video", "image", "audio", "视觉"),
        "研究趋势": ("paper", "benchmark", "研究", "论文", "评测"),
        "公司动态": ("funding", "pricing", "acquisition", "融资", "收购", "合作"),
    }
    lowered = markdown.lower()
    for label, needles in keyword_map.items():
        if any(needle in lowered for needle in needles):
            candidates.append(label)
    if not candidates:
        candidates = ["AI日报", "产品发布", "开源工具", "研究趋势"]
    return candidates


def extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def extract_digest(markdown: str) -> str:
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    body_lines = [line for line in lines if not line.startswith("#") and not line.startswith(">")]
    digest = " ".join(body_lines[:4]).strip()
    return clamp_digest(digest)


def clamp_digest(text: str, max_chars: int = 110, max_bytes: int = 320) -> str:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return ""
    shortened = trim(cleaned, max_chars)
    while len(shortened.encode("utf-8")) > max_bytes and len(shortened) > 10:
        shortened = trim(shortened, max(20, len(shortened) - 10))
    return shortened


def markdown_to_wechat_html(markdown: str, *, cover_meta: dict[str, Any]) -> str:
    content_lines = markdown.splitlines()
    html_lines = [
        '<section style="max-width:720px;margin:0 auto;padding:0 0 32px;color:#18212f;font-size:16px;line-height:1.9;background:#ffffff;">',
        build_hero_block(cover_meta),
    ]

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

    for raw_line in content_lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            close_list()
            close_blockquote()
            continue

        if stripped.startswith("# "):
            continue

        if stripped.startswith("> "):
            close_list()
            if not in_blockquote:
                html_lines.append(
                    '<blockquote style="margin:18px 0;padding:14px 18px;background:#f5f8ff;border-left:4px solid #3b82f6;border-radius:0 12px 12px 0;color:#334155;">'
                )
                in_blockquote = True
            html_lines.append(f'<p style="margin:0;">{format_inline(stripped[2:].strip())}</p>')
            continue

        close_blockquote()

        if stripped.startswith("- "):
            if not in_list:
                html_lines.append('<ul style="padding-left:22px;margin:14px 0 18px;">')
                in_list = True
            html_lines.append(f'<li style="margin:8px 0;">{format_inline(stripped[2:].strip())}</li>')
            continue

        close_list()

        if stripped.startswith("## "):
            html_lines.append(build_section_heading(stripped[3:].strip()))
            continue
        if stripped.startswith("### "):
            html_lines.append(build_story_heading(stripped[4:].strip()))
            continue

        label_match = STRONG_LABEL_RE.match(stripped)
        if label_match:
            label = html.escape(label_match.group(1), quote=False)
            value = format_inline(label_match.group(2))
            html_lines.append(
                '<p style="margin:10px 0 12px;font-size:15px;line-height:1.9;color:#1f2937;">'
                f'<strong style="color:#0f172a;">{label}：</strong>{value}</p>'
            )
            continue

        html_lines.append(
            f'<p style="margin:10px 0;color:#1f2937;font-size:15px;line-height:1.95;">{format_inline(stripped)}</p>'
        )

    close_list()
    close_blockquote()
    html_lines.append(
        '<p style="margin-top:28px;padding-top:18px;border-top:1px solid #e5e7eb;color:#64748b;font-size:13px;">'
        f'封面图 AI 提示词：{html.escape(cover_meta.get("cover_prompt", ""), quote=False)}</p>'
    )
    html_lines.append("</section>")
    return "\n".join(html_lines)


def build_hero_block(cover_meta: dict[str, Any]) -> str:
    title = html.escape(cover_meta.get("cover_title", "AI Daily Scout"), quote=False)
    subtitle = html.escape(cover_meta.get("cover_subtitle", ""), quote=False)
    keywords = " · ".join(html.escape(keyword, quote=False) for keyword in cover_meta.get("cover_keywords", []))
    return (
        '<section style="padding:28px 24px 24px;border-radius:24px;background:linear-gradient(135deg,#0f172a 0%,#102a43 45%,#1d4ed8 100%);'
        'color:#f8fafc;margin:0 0 28px;box-shadow:0 18px 36px rgba(15,23,42,0.18);">'
        '<div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#93c5fd;margin-bottom:10px;">AI Daily Scout</div>'
        f'<h1 style="margin:0 0 10px;font-size:30px;line-height:1.35;font-weight:800;color:#ffffff;">{title}</h1>'
        f'<p style="margin:0 0 12px;font-size:15px;line-height:1.8;color:#dbeafe;">{subtitle}</p>'
        f'<p style="margin:0;font-size:13px;line-height:1.7;color:#bfdbfe;">{keywords}</p>'
        '</section>'
    )


def build_section_heading(text: str) -> str:
    return (
        '<h2 style="margin:30px 0 14px;padding-left:14px;border-left:5px solid #2563eb;'
        'font-size:24px;line-height:1.5;font-weight:800;color:#0f172a;">'
        f"{format_inline(text)}</h2>"
    )


def build_story_heading(text: str) -> str:
    return (
        '<h3 style="margin:24px 0 12px;padding:14px 16px;border-radius:16px;background:#f8fafc;'
        'font-size:19px;line-height:1.6;font-weight:800;color:#0f172a;border:1px solid #e5e7eb;">'
        f"{format_inline(text)}</h3>"
    )


def format_inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = LINK_RE.sub(
        lambda match: f'<a href="{html.escape(match.group(2), quote=True)}" style="color:#2563eb;text-decoration:none;border-bottom:1px solid #93c5fd;">{html.escape(match.group(1), quote=False)}</a>',
        escaped,
    )
    return escaped


def trim(text: str, limit: int) -> str:
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip("，,;； ") + "…"


def guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"
