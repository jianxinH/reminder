from __future__ import annotations

import os
from pathlib import Path

from app.scout.delivery.wechat_mp_sender import send_report_to_wechat_mp


def main() -> None:
    report_path = os.environ["SCOUT_REPORT_PATH"]
    app_id = os.environ.get("WECHAT_MP_APP_ID", "")
    app_secret = os.environ.get("WECHAT_MP_APP_SECRET", "")
    author = os.environ.get("WECHAT_MP_AUTHOR", "AI Daily Scout")
    thumb_media_id = os.environ.get("WECHAT_MP_THUMB_MEDIA_ID", "")
    digest = os.environ.get("WECHAT_MP_DIGEST", "")
    content_source_url = os.environ.get("WECHAT_MP_CONTENT_SOURCE_URL", "")
    base_url = os.environ.get("WECHAT_MP_BASE_URL", "https://api.weixin.qq.com")
    auto_generate_cover = os.environ.get("WECHAT_MP_AUTO_GENERATE_COVER", "").strip().lower() in {"1", "true", "yes", "on"}
    cover_image_api_key = os.environ.get("WECHAT_MP_COVER_IMAGE_API_KEY", "")
    cover_image_model = os.environ.get("WECHAT_MP_COVER_IMAGE_MODEL", "gpt-image-1")
    cover_image_base_url = os.environ.get("WECHAT_MP_COVER_IMAGE_BASE_URL", "https://api.openai.com/v1")
    cover_image_size = os.environ.get("WECHAT_MP_COVER_IMAGE_SIZE", "1536x1024")
    cover_image_quality = os.environ.get("WECHAT_MP_COVER_IMAGE_QUALITY", "high")

    path = Path(report_path)
    if not path.exists():
        raise FileNotFoundError(f"Report not found: {path}")

    payload = send_report_to_wechat_mp(
        report_path=str(path),
        app_id=app_id,
        app_secret=app_secret,
        author=author,
        thumb_media_id=thumb_media_id,
        digest=digest,
        content_source_url=content_source_url,
        base_url=base_url,
        auto_generate_cover=auto_generate_cover,
        cover_image_api_key=cover_image_api_key,
        cover_image_model=cover_image_model,
        cover_image_base_url=cover_image_base_url,
        cover_image_size=cover_image_size,
        cover_image_quality=cover_image_quality,
    )
    print("WECHAT_MP_DRAFT_OK")
    if payload.get("media_id"):
        print(f"media_id={payload['media_id']}")
    if payload.get("local_meta_path"):
        print(f"local_meta_path={payload['local_meta_path']}")
    if payload.get("generated_cover_path"):
        print(f"generated_cover_path={payload['generated_cover_path']}")
    if payload.get("cover_prompt"):
        print(f"cover_prompt={payload['cover_prompt']}")


if __name__ == "__main__":
    main()
