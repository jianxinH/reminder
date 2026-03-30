from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


class ArticleRepository:
    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path)

    def exists_by_url(self, url: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute("SELECT 1 FROM articles WHERE url = ? LIMIT 1", (url,)).fetchone()
            return row is not None
        finally:
            conn.close()

    def insert_article(self, item: dict) -> int:
        now = timestamp()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO articles (
                    title, url, source, published_at, summary, raw_category,
                    content_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.get("title", ""),
                    item.get("url", ""),
                    item.get("source", ""),
                    item.get("published_at", ""),
                    item.get("summary", ""),
                    item.get("raw_category", ""),
                    item.get("content_hash", ""),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def insert_article_summary(self, article_id: int, summary: dict) -> None:
        now = timestamp()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO article_summaries (
                    article_id, zh_title, category_suggestion, short_summary,
                    why_it_matters, include_in_report, importance_score,
                    confidence, tags, model_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_id,
                    summary.get("zh_title", ""),
                    summary.get("category_suggestion", ""),
                    summary.get("short_summary", ""),
                    summary.get("why_it_matters", ""),
                    1 if summary.get("include_in_report", True) else 0,
                    int(summary.get("importance_score", 50)),
                    float(summary.get("confidence", 0.0)),
                    json.dumps(summary.get("tags", []), ensure_ascii=False),
                    summary.get("model_name", ""),
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_report(self, report_path: Path, item_count: int) -> None:
        now = timestamp()
        report_date = report_path.stem
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO reports (
                    id, report_date, title, file_path, item_count, created_at
                ) VALUES (
                    (SELECT id FROM reports WHERE report_date = ?),
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    report_date,
                    report_date,
                    f"AI Daily Scout 日报 - {report_date}",
                    str(report_path),
                    item_count,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn


def timestamp() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")
