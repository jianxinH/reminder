from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
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

    def get_recent_report_items(self, recent_days: int, limit: int) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    a.id,
                    a.title,
                    a.url,
                    a.source,
                    a.published_at,
                    a.summary,
                    a.raw_category,
                    s.zh_title,
                    s.category_suggestion,
                    s.short_summary,
                    s.why_it_matters,
                    s.include_in_report,
                    s.importance_score,
                    s.confidence,
                    s.tags,
                    s.model_name
                FROM articles a
                LEFT JOIN article_summaries s
                    ON s.article_id = a.id
                WHERE a.published_at >= ?
                ORDER BY COALESCE(s.importance_score, 50) DESC, a.published_at DESC, a.id DESC
                LIMIT ?
                """,
                (cutoff_timestamp(recent_days), limit),
            ).fetchall()
            items: list[dict] = []
            for row in rows:
                items.append(
                    {
                        "title": row["title"],
                        "url": row["url"],
                        "source": row["source"],
                        "published_at": row["published_at"],
                        "summary": row["summary"],
                        "raw_category": row["raw_category"],
                        "zh_title": row["zh_title"] or row["title"],
                        "category_suggestion": row["category_suggestion"] or row["raw_category"] or "其他",
                        "short_summary": row["short_summary"] or row["summary"] or row["title"],
                        "why_it_matters": row["why_it_matters"] or "来自数据库的近期已存内容。",
                        "include_in_report": bool(row["include_in_report"]) if row["include_in_report"] is not None else True,
                        "importance_score": row["importance_score"] if row["importance_score"] is not None else 50,
                        "confidence": row["confidence"] if row["confidence"] is not None else 0.0,
                        "tags": parse_tags(row["tags"]),
                        "model_name": row["model_name"] or "",
                    }
                )
            return items
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn


def timestamp() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def cutoff_timestamp(recent_days: int) -> str:
    cutoff = datetime.utcnow() - timedelta(days=max(0, recent_days))
    return cutoff.replace(microsecond=0).isoformat(timespec="seconds")


def parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
