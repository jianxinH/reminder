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

    path = Path(report_path)
    if not path.exists():
        raise FileNotFoundError(f"Report not found: {path}")

    send_report_to_wechat_mp(
        report_path=str(path),
        app_id=app_id,
        app_secret=app_secret,
        author=author,
        thumb_media_id=thumb_media_id,
        digest=digest,
        content_source_url=content_source_url,
        base_url=base_url,
    )


if __name__ == "__main__":
    main()
