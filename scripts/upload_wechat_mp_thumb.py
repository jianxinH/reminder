from __future__ import annotations

import os
import sys
from pathlib import Path

from app.scout.delivery.wechat_mp_sender import upload_wechat_mp_thumb


def main() -> None:
    image_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WECHAT_MP_THUMB_IMAGE_PATH", "")
    if not image_path:
        raise RuntimeError("Missing thumb image path. Pass it as argv[1] or WECHAT_MP_THUMB_IMAGE_PATH.")

    app_id = os.environ.get("WECHAT_MP_APP_ID", "")
    app_secret = os.environ.get("WECHAT_MP_APP_SECRET", "")
    base_url = os.environ.get("WECHAT_MP_BASE_URL", "https://api.weixin.qq.com")

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Thumb image not found: {path}")

    payload = upload_wechat_mp_thumb(
        image_path=str(path),
        app_id=app_id,
        app_secret=app_secret,
        base_url=base_url,
    )

    media_id = payload.get("media_id", "")
    url = payload.get("url", "")
    print("UPLOAD_OK")
    print(f"media_id={media_id}")
    if url:
        print(f"url={url}")


if __name__ == "__main__":
    main()
