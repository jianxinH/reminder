from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def write_markdown_report(content: str, output_dir: str, timezone_name: str) -> Path:
    tz = ZoneInfo(timezone_name)
    report_date = datetime.now(tz).date().isoformat()
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    report_path = target_dir / f"{report_date}.md"
    report_path.write_text(content, encoding="utf-8")
    return report_path
