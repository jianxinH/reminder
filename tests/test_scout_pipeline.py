from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scout.config.settings import get_settings
from app.scout.delivery.markdown_writer import write_markdown_report
from app.scout.delivery.wecom_sender import build_wecom_message
from app.scout.fetchers.rss_fetcher import fetch_all_rss_items
from app.scout.main import filter_recent_items, run_pipeline
from app.scout.pipeline.classify import classify_items
from app.scout.pipeline.dedupe import dedupe_items
from app.scout.pipeline.normalize import normalize_items
from app.scout.pipeline.summarize import NewsSummarizer
from app.scout.storage.db import init_db
from app.scout.storage.repository import ArticleRepository


class ScoutPipelineTests(unittest.TestCase):
    def test_normalize_and_dedupe(self) -> None:
        raw_items = [
            {
                "title": "OpenAI launches new model",
                "url": "https://example.com/a",
                "source": "Example",
                "summary": "<p>New model is here.</p>",
                "raw_category": "product",
            },
            {
                "title": "OpenAI launches new model",
                "url": "https://example.com/b",
                "source": "Example",
                "summary": "New model is here.",
                "raw_category": "product",
            },
        ]

        normalized = normalize_items(raw_items)
        unique_items = dedupe_items(normalized)

        self.assertEqual(2, len(normalized))
        self.assertEqual(1, len(unique_items))
        self.assertTrue(unique_items[0]["content_hash"])

    def test_classify_items(self) -> None:
        items = classify_items(
            [
                {
                    "title": "Open source agent toolkit",
                    "summary": "A new GitHub repository for agent workflows",
                    "raw_category": "",
                }
            ]
        )
        self.assertIn(items[0]["category"], {"开源", "应用"})

    def test_filter_recent_items(self) -> None:
        items = [
            {"title": "Recent", "published_at": "2026-03-30T08:00:00+08:00"},
            {"title": "Old", "published_at": "2026-03-20T08:00:00+08:00"},
            {"title": "Missing", "published_at": ""},
        ]
        filtered = filter_recent_items(items, recent_days=3, timezone_name="Asia/Shanghai")
        self.assertEqual(["Recent"], [item["title"] for item in filtered])

    def test_repository_and_report_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "scout.db"
            init_db(str(db_path))
            repository = ArticleRepository(str(db_path))

            article_id = repository.insert_article(
                {
                    "title": "Test title",
                    "url": "https://example.com/test",
                    "source": "Example",
                    "published_at": "",
                    "summary": "Summary",
                    "raw_category": "news",
                    "content_hash": "hash-1",
                }
            )
            repository.insert_article_summary(
                article_id,
                {
                    "zh_title": "测试标题",
                    "category_suggestion": "产品",
                    "short_summary": "摘要",
                    "why_it_matters": "有参考价值",
                    "include_in_report": True,
                    "importance_score": 80,
                    "confidence": 0.8,
                    "tags": ["测试"],
                    "model_name": "mock-model",
                },
            )
            self.assertTrue(repository.exists_by_url("https://example.com/test"))

            report_path = write_markdown_report("# demo", tmpdir, "Asia/Shanghai")
            repository.insert_report(report_path, item_count=1)
            self.assertTrue(report_path.exists())

    def test_build_wecom_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "2026-03-30.md"
            report_path.write_text(
                "# AI Daily Scout 日报 - 2026-03-30\n\n"
                "## 今日概览\n\n"
                "### 1. 开源 Agent 工具包\n\n"
                "- 摘要：一个新的开源 Agent 工具包发布。\n\n"
                "### 2. 新模型发布\n\n"
                "- 摘要：一个新的模型版本上线。\n",
                encoding="utf-8",
            )

            message = build_wecom_message(
                report_path=str(report_path),
                report_url="https://github.com/example/reports/2026-03-30.md",
            )

            self.assertIn("AI Daily Scout 日报 - 2026-03-30", message)
            self.assertIn("1. 开源 Agent 工具包", message)
            self.assertIn("完整日报：https://github.com/example/reports/2026-03-30.md", message)

    def test_fetch_all_rss_items_with_mocked_network(self) -> None:
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>AI launch</title>
      <link>https://example.com/news/1</link>
      <description>New AI release</description>
      <pubDate>Mon, 30 Mar 2026 10:00:00 GMT</pubDate>
      <category>product</category>
    </item>
  </channel>
</rss>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sources_file = Path(tmpdir) / "sources.yaml"
            sources_file.write_text(
                "sources:\n  - name: Example\n    url: https://example.com/rss.xml\n    enabled: true\n",
                encoding="utf-8",
            )

            class MockResponse:
                text = rss_xml

                def raise_for_status(self) -> None:
                    return None

            with patch("app.scout.fetchers.rss_fetcher.httpx.get", return_value=MockResponse()):
                items = fetch_all_rss_items(str(sources_file))

            self.assertEqual(1, len(items))
            self.assertEqual("AI launch", items[0]["title"])
            self.assertEqual("https://example.com/news/1", items[0]["url"])
            self.assertEqual("Example", items[0]["source"])

    def test_summarizer_falls_back_when_openai_request_fails(self) -> None:
        summarizer = NewsSummarizer(api_key="test-key", model="gpt-5.4")
        item = {
            "title": "OpenAI launches new model",
            "summary": "Original summary",
            "category": "模型",
            "source": "Example",
            "published_at": "",
            "url": "https://example.com/a",
        }

        with patch(
            "app.scout.pipeline.summarize.httpx.post",
            side_effect=RuntimeError("network down"),
        ):
            result = summarizer.summarize_item(item)

        self.assertEqual("OpenAI launches new model", result["zh_title"])
        self.assertEqual("Original summary", result["short_summary"])
        self.assertEqual("模型摘要不可用，已回退为原始内容。", result["why_it_matters"])
        self.assertTrue(result["include_in_report"])

    def test_run_pipeline_end_to_end_with_recent_filter_and_summary_limit(self) -> None:
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>Open source agent toolkit</title>
      <link>https://example.com/news/agent-toolkit</link>
      <description>GitHub released a new open source agent toolkit.</description>
      <pubDate>Mon, 30 Mar 2026 10:00:00 GMT</pubDate>
      <category>open source</category>
    </item>
    <item>
      <title>Historical AI note</title>
      <link>https://example.com/news/old-note</link>
      <description>Older item that should be filtered out.</description>
      <pubDate>Mon, 10 Feb 2026 10:00:00 GMT</pubDate>
      <category>research</category>
    </item>
  </channel>
</rss>
"""
        summary_payload = {
            "output_text": (
                '{"zh_title":"开源 Agent 工具包","category_suggestion":"开源",'
                '"short_summary":"一个新的开源 Agent 工具包发布。",'
                '"why_it_matters":"适合关注 Agent 工程实践。",'
                '"include_in_report":true,"importance_score":85,'
                '"confidence":0.9,"tags":["agent","open-source"]}'
            )
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "data").mkdir()
            (project_dir / "reports").mkdir()

            sources_file = project_dir / "sources.yaml"
            db_path = project_dir / "data" / "scout.db"
            sources_file.write_text(
                "sources:\n  - name: Example\n    url: https://example.com/rss.xml\n    enabled: true\n",
                encoding="utf-8",
            )

            class MockGetResponse:
                text = rss_xml

                def raise_for_status(self) -> None:
                    return None

            class MockPostResponse:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict:
                    return summary_payload

            old_cwd = os.getcwd()
            old_env = {
                key: os.environ.get(key)
                for key in (
                    "OPENAI_API_KEY",
                    "OPENAI_MODEL",
                    "SCOUT_DATABASE_PATH",
                    "SCOUT_SOURCES_FILE",
                    "REPORT_TIMEZONE",
                    "REPORT_LANGUAGE",
                    "REPORT_TOP_N",
                    "SCOUT_RECENT_DAYS",
                    "SCOUT_MAX_SUMMARY_ITEMS",
                    "SCOUT_LOG_LEVEL",
                )
            }
            try:
                os.chdir(project_dir)
                os.environ["OPENAI_API_KEY"] = "test-key"
                os.environ["OPENAI_MODEL"] = "gpt-5.4"
                os.environ["SCOUT_DATABASE_PATH"] = str(db_path)
                os.environ["SCOUT_SOURCES_FILE"] = str(sources_file)
                os.environ["REPORT_TIMEZONE"] = "Asia/Shanghai"
                os.environ["REPORT_LANGUAGE"] = "zh-CN"
                os.environ["REPORT_TOP_N"] = "20"
                os.environ["SCOUT_RECENT_DAYS"] = "30"
                os.environ["SCOUT_MAX_SUMMARY_ITEMS"] = "1"
                os.environ["SCOUT_LOG_LEVEL"] = "INFO"
                get_settings.cache_clear()

                with patch("app.scout.fetchers.rss_fetcher.httpx.get", return_value=MockGetResponse()):
                    with patch("app.scout.pipeline.summarize.httpx.post", return_value=MockPostResponse()) as mock_post:
                        stats = run_pipeline()
            finally:
                os.chdir(old_cwd)
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                get_settings.cache_clear()

            self.assertEqual(2, stats["fetched_count"])
            self.assertEqual(2, stats["normalized_count"])
            self.assertEqual(1, stats["recent_count"])
            self.assertEqual(1, stats["deduped_count"])
            self.assertEqual(1, stats["inserted_count"])
            self.assertEqual(1, stats["summarized_count"])
            self.assertEqual(1, stats["included_count"])
            self.assertEqual(1, mock_post.call_count)

            report_path = project_dir / stats["report_path"]
            self.assertTrue(report_path.exists())
            report_content = report_path.read_text(encoding="utf-8")
            self.assertIn("开源 Agent 工具包", report_content)
            self.assertIn("适合关注 Agent 工程实践。", report_content)

    def test_run_pipeline_rebuilds_report_from_database_when_no_new_items(self) -> None:
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>Open source agent toolkit</title>
      <link>https://example.com/news/agent-toolkit</link>
      <description>GitHub released a new open source agent toolkit.</description>
      <pubDate>Mon, 30 Mar 2026 10:00:00 GMT</pubDate>
      <category>open source</category>
    </item>
  </channel>
</rss>
"""
        summary_payload = {
            "output_text": (
                '{"zh_title":"开源 Agent 工具包","category_suggestion":"开源",'
                '"short_summary":"一个新的开源 Agent 工具包发布。",'
                '"why_it_matters":"适合关注 Agent 工程实践。",'
                '"include_in_report":true,"importance_score":85,'
                '"confidence":0.9,"tags":["agent","open-source"]}'
            )
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "data").mkdir()
            (project_dir / "reports").mkdir()

            sources_file = project_dir / "sources.yaml"
            db_path = project_dir / "data" / "scout.db"
            sources_file.write_text(
                "sources:\n  - name: Example\n    url: https://example.com/rss.xml\n    enabled: true\n",
                encoding="utf-8",
            )

            class MockGetResponse:
                text = rss_xml

                def raise_for_status(self) -> None:
                    return None

            class MockPostResponse:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict:
                    return summary_payload

            old_cwd = os.getcwd()
            old_env = {
                key: os.environ.get(key)
                for key in (
                    "OPENAI_API_KEY",
                    "OPENAI_MODEL",
                    "SCOUT_DATABASE_PATH",
                    "SCOUT_SOURCES_FILE",
                    "REPORT_TIMEZONE",
                    "REPORT_LANGUAGE",
                    "REPORT_TOP_N",
                    "SCOUT_RECENT_DAYS",
                    "SCOUT_MAX_SUMMARY_ITEMS",
                    "SCOUT_LOG_LEVEL",
                )
            }
            try:
                os.chdir(project_dir)
                os.environ["OPENAI_API_KEY"] = "test-key"
                os.environ["OPENAI_MODEL"] = "gpt-5.4"
                os.environ["SCOUT_DATABASE_PATH"] = str(db_path)
                os.environ["SCOUT_SOURCES_FILE"] = str(sources_file)
                os.environ["REPORT_TIMEZONE"] = "Asia/Shanghai"
                os.environ["REPORT_LANGUAGE"] = "zh-CN"
                os.environ["REPORT_TOP_N"] = "20"
                os.environ["SCOUT_RECENT_DAYS"] = "30"
                os.environ["SCOUT_MAX_SUMMARY_ITEMS"] = "1"
                os.environ["SCOUT_LOG_LEVEL"] = "INFO"
                get_settings.cache_clear()

                with patch("app.scout.fetchers.rss_fetcher.httpx.get", return_value=MockGetResponse()):
                    with patch("app.scout.pipeline.summarize.httpx.post", return_value=MockPostResponse()):
                        first_stats = run_pipeline()

                with patch("app.scout.fetchers.rss_fetcher.httpx.get", return_value=MockGetResponse()):
                    with patch("app.scout.pipeline.summarize.httpx.post", return_value=MockPostResponse()) as mock_post:
                        second_stats = run_pipeline()
            finally:
                os.chdir(old_cwd)
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                get_settings.cache_clear()

            self.assertEqual(1, first_stats["inserted_count"])
            self.assertEqual(0, second_stats["inserted_count"])
            self.assertEqual(0, second_stats["summarized_count"])
            self.assertEqual(1, second_stats["included_count"])
            self.assertEqual(1, second_stats["rebuilt_from_db_count"])
            self.assertEqual(0, mock_post.call_count)


if __name__ == "__main__":
    unittest.main()
