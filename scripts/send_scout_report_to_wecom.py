from __future__ import annotations

import os
from pathlib import Path

from app.scout.delivery.wecom_sender import send_report_to_wecom


def main() -> None:
    report_path = os.environ["SCOUT_REPORT_PATH"]
    corp_id = os.environ["WECOM_CORP_ID"]
    agent_id = os.environ["WECOM_AGENT_ID"]
    secret = os.environ["WECOM_SECRET"]
    touser = os.environ["WECOM_TOUSER"]
    base_url = os.environ.get("WECOM_BASE_URL", "https://qyapi.weixin.qq.com")
    report_url = os.environ.get("SCOUT_REPORT_URL", "")

    path = Path(report_path)
    if not path.exists():
        raise FileNotFoundError(f"Report not found: {path}")

    send_report_to_wecom(
        report_path=str(path),
        corp_id=corp_id,
        agent_id=agent_id,
        secret=secret,
        touser=touser,
        base_url=base_url,
        report_url=report_url,
    )


if __name__ == "__main__":
    main()
