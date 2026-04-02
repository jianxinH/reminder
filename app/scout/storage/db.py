from __future__ import annotations

import sqlite3
from pathlib import Path


def init_db(database_path: str) -> None:
    db_file = Path(database_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_file)
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                source TEXT,
                source_type TEXT,
                source_language TEXT,
                published_at TEXT,
                summary TEXT,
                raw_category TEXT,
                category_hint TEXT,
                priority INTEGER DEFAULT 50,
                content_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_articles_published_at
            ON articles (published_at)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_articles_source
            ON articles (source)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_articles_content_hash
            ON articles (content_hash)
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS article_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                is_ai_related INTEGER NOT NULL DEFAULT 1,
                zh_title TEXT,
                category_suggestion TEXT,
                one_line_takeaway TEXT,
                what_happened TEXT,
                why_it_matters TEXT,
                who_should_care TEXT,
                my_commentary TEXT,
                short_summary TEXT,
                include_in_report INTEGER NOT NULL DEFAULT 1,
                importance_score INTEGER DEFAULT 50,
                confidence REAL DEFAULT 0.0,
                tags TEXT,
                related_sources TEXT,
                model_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (article_id) REFERENCES articles(id)
            )
            """
        )

        ensure_column(cursor, "article_summaries", "is_ai_related", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(cursor, "article_summaries", "one_line_takeaway", "TEXT")
        ensure_column(cursor, "article_summaries", "what_happened", "TEXT")
        ensure_column(cursor, "article_summaries", "who_should_care", "TEXT")
        ensure_column(cursor, "article_summaries", "my_commentary", "TEXT")
        ensure_column(cursor, "article_summaries", "short_summary", "TEXT")
        ensure_column(cursor, "article_summaries", "related_sources", "TEXT")
        ensure_column(cursor, "articles", "source_type", "TEXT")
        ensure_column(cursor, "articles", "source_language", "TEXT")
        ensure_column(cursor, "articles", "category_hint", "TEXT")
        ensure_column(cursor, "articles", "priority", "INTEGER DEFAULT 50")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                file_path TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.commit()
    finally:
        conn.close()


def ensure_column(cursor: sqlite3.Cursor, table_name: str, column_name: str, definition: str) -> None:
    columns = {
        row[1]
        for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name in columns:
        return
    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
