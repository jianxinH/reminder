from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ARTICLE_SELECT = """
    SELECT
        a.id,
        a.title,
        a.clean_title,
        a.normalized_title,
        a.url,
        a.canonical_url,
        a.source,
        a.source_type,
        a.source_language,
        a.published_at,
        a.published_date,
        a.discovered_date,
        a.summary,
        a.raw_category,
        a.category_hint,
        a.priority,
        a.content_hash,
        s.is_ai_related,
        s.zh_title,
        s.category_suggestion,
        s.one_line_takeaway,
        s.what_happened,
        s.why_it_matters,
        s.who_should_care,
        s.my_commentary,
        s.short_summary,
        s.display_section,
        s.trend_type,
        s.summary_zh,
        s.why_it_matters_zh,
        s.target_audience_zh,
        s.topic_tags,
        s.quality_score,
        s.editorial_score,
        s.cluster_id,
        s.related_links,
        s.include_in_report,
        s.importance_score,
        s.confidence,
        s.tags,
        s.related_sources,
        s.generated_by_model,
        s.model_name
    FROM articles a
    LEFT JOIN article_summaries s ON s.article_id = a.id
"""


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

    def get_article_id_by_url(self, url: str) -> int | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id FROM articles WHERE url = ? ORDER BY id DESC LIMIT 1",
                (url,),
            ).fetchone()
            return int(row["id"]) if row else None
        finally:
            conn.close()

    def insert_article(self, item: dict[str, Any]) -> int:
        now = timestamp()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO articles (
                    title,
                    clean_title,
                    normalized_title,
                    url,
                    canonical_url,
                    source,
                    source_type,
                    source_language,
                    published_at,
                    published_date,
                    discovered_date,
                    summary,
                    raw_category,
                    category_hint,
                    priority,
                    content_hash,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.get("title", ""),
                    item.get("clean_title", ""),
                    item.get("normalized_title", ""),
                    item.get("url", ""),
                    item.get("canonical_url", ""),
                    item.get("source", ""),
                    item.get("source_type", ""),
                    item.get("source_language", ""),
                    item.get("published_at", ""),
                    item.get("published_date", ""),
                    item.get("discovered_date", ""),
                    item.get("summary", ""),
                    item.get("raw_category", ""),
                    item.get("category_hint", ""),
                    int(item.get("priority", 50)),
                    item.get("content_hash", ""),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def insert_article_summary(self, article_id: int, summary: dict[str, Any]) -> None:
        now = timestamp()
        conn = self._connect()
        try:
            conn.execute("DELETE FROM article_summaries WHERE article_id = ?", (article_id,))
            conn.execute(
                """
                INSERT INTO article_summaries (
                    article_id,
                    is_ai_related,
                    zh_title,
                    category_suggestion,
                    one_line_takeaway,
                    what_happened,
                    why_it_matters,
                    who_should_care,
                    my_commentary,
                    short_summary,
                    display_section,
                    trend_type,
                    summary_zh,
                    why_it_matters_zh,
                    target_audience_zh,
                    topic_tags,
                    quality_score,
                    editorial_score,
                    cluster_id,
                    related_links,
                    include_in_report,
                    importance_score,
                    confidence,
                    tags,
                    related_sources,
                    generated_by_model,
                    model_name,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article_id,
                    1 if summary.get("is_ai_related", True) else 0,
                    summary.get("zh_title", ""),
                    summary.get("category_suggestion", ""),
                    summary.get("one_line_takeaway", ""),
                    summary.get("what_happened", ""),
                    summary.get("why_it_matters", ""),
                    summary.get("who_should_care", ""),
                    summary.get("my_commentary", ""),
                    summary.get("short_summary", ""),
                    summary.get("display_section", ""),
                    summary.get("trend_type", ""),
                    summary.get("summary_zh", ""),
                    summary.get("why_it_matters_zh", summary.get("why_it_matters", "")),
                    json.dumps(summary.get("target_audience_zh", []), ensure_ascii=False),
                    json.dumps(summary.get("topic_tags", []), ensure_ascii=False),
                    int(summary.get("quality_score", 0)),
                    float(summary.get("editorial_score", 0.0)),
                    summary.get("cluster_id", ""),
                    json.dumps(summary.get("related_links", []), ensure_ascii=False),
                    1 if summary.get("include_in_report", True) else 0,
                    int(summary.get("importance_score", 50)),
                    float(summary.get("confidence", 0.0)),
                    json.dumps(summary.get("tags", []), ensure_ascii=False),
                    json.dumps(summary.get("related_sources", []), ensure_ascii=False),
                    1 if summary.get("generated_by_model", False) else 0,
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

    def get_recent_report_items(self, recent_days: int, limit: int) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                {ARTICLE_SELECT}
                WHERE
                    a.published_at >= ?
                    OR ((a.published_at IS NULL OR a.published_at = '') AND a.created_at >= ?)
                ORDER BY
                    COALESCE(s.editorial_score, 0.0) DESC,
                    COALESCE(s.importance_score, 50) DESC,
                    COALESCE(NULLIF(a.published_at, ''), a.created_at) DESC,
                    a.id DESC
                LIMIT ?
                """,
                (cutoff_timestamp(recent_days), cutoff_timestamp(recent_days), limit),
            ).fetchall()
            return [self._row_to_item(row) for row in rows]
        finally:
            conn.close()

    def get_items_by_urls(self, urls: list[str], limit: int | None = None) -> list[dict[str, Any]]:
        clean_urls = [url for url in urls if url]
        if not clean_urls:
            return []

        placeholders = ",".join("?" for _ in clean_urls)
        sql = f"""
            {ARTICLE_SELECT}
            WHERE a.url IN ({placeholders})
            ORDER BY
                COALESCE(s.editorial_score, 0.0) DESC,
                COALESCE(s.importance_score, 50) DESC,
                COALESCE(NULLIF(a.published_at, ''), a.created_at) DESC,
                a.id DESC
        """
        params: list[Any] = list(clean_urls)
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_item(row) for row in rows]
        finally:
            conn.close()

    def _row_to_item(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "clean_title": row["clean_title"] or row["title"],
            "normalized_title": row["normalized_title"] or "",
            "url": row["url"],
            "canonical_url": row["canonical_url"] or row["url"],
            "source": row["source"],
            "source_name": row["source"],
            "source_type": row["source_type"] or "",
            "source_language": row["source_language"] or "",
            "published_at": row["published_at"],
            "published_date": row["published_date"] or (row["published_at"] or "")[:10],
            "discovered_date": row["discovered_date"] or "",
            "summary": row["summary"],
            "raw_category": row["raw_category"],
            "category_hint": row["category_hint"] or "",
            "priority": row["priority"] if row["priority"] is not None else 50,
            "content_hash": row["content_hash"],
            "is_ai_related": bool(row["is_ai_related"]) if row["is_ai_related"] is not None else True,
            "zh_title": row["zh_title"] or row["clean_title"] or row["title"],
            "category_suggestion": row["category_suggestion"] or row["raw_category"] or "其他",
            "one_line_takeaway": row["one_line_takeaway"] or row["short_summary"] or row["summary"] or row["title"],
            "what_happened": row["what_happened"] or "",
            "why_it_matters": row["why_it_matters"] or "",
            "who_should_care": row["who_should_care"] or "",
            "my_commentary": row["my_commentary"] or "",
            "short_summary": row["short_summary"] or row["summary"] or row["title"],
            "display_section": row["display_section"] or "",
            "trend_type": row["trend_type"] or "",
            "summary_zh": row["summary_zh"] or row["one_line_takeaway"] or row["summary"] or "",
            "why_it_matters_zh": row["why_it_matters_zh"] or row["why_it_matters"] or "",
            "target_audience_zh": parse_json_list(row["target_audience_zh"]),
            "topic_tags": parse_json_list(row["topic_tags"]),
            "quality_score": row["quality_score"] if row["quality_score"] is not None else 0,
            "editorial_score": row["editorial_score"] if row["editorial_score"] is not None else 0.0,
            "cluster_id": row["cluster_id"] or "",
            "related_links": parse_json_list(row["related_links"]),
            "include_in_report": bool(row["include_in_report"]) if row["include_in_report"] is not None else True,
            "importance_score": row["importance_score"] if row["importance_score"] is not None else 50,
            "confidence": row["confidence"] if row["confidence"] is not None else 0.0,
            "tags": parse_json_list(row["tags"]),
            "related_sources": parse_json_list(row["related_sources"]),
            "generated_by_model": bool(row["generated_by_model"]) if row["generated_by_model"] is not None else False,
            "model_name": row["model_name"] or "",
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn


def timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def cutoff_timestamp(recent_days: int) -> str:
    cutoff = datetime.utcnow() - timedelta(days=max(0, recent_days))
    return cutoff.replace(microsecond=0).isoformat()


def parse_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
