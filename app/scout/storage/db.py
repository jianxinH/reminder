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
                published_at TEXT,
                summary TEXT,
                raw_category TEXT,
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
                zh_title TEXT,
                category_suggestion TEXT,
                short_summary TEXT,
                why_it_matters TEXT,
                include_in_report INTEGER NOT NULL DEFAULT 1,
                importance_score INTEGER DEFAULT 50,
                confidence REAL DEFAULT 0.0,
                tags TEXT,
                model_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (article_id) REFERENCES articles(id)
            )
            """
        )
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
