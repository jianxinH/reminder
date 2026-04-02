from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SummaryCard:
    title: str
    url: str
    source: str = ""
    published_at: str = ""
    category_suggestion: str = "其他"
    zh_title: str = ""
    one_line_takeaway: str = ""
    what_happened: str = ""
    why_it_matters: str = ""
    who_should_care: str = ""
    my_commentary: str = ""
    include_in_report: bool = True
    is_ai_related: bool = True
    importance_score: int = 50
    confidence: float = 0.0
    tags: list[str] = field(default_factory=list)
    related_sources: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DailyEditorialSummary:
    overview: str
    top_stories: list[str] = field(default_factory=list)
    trend_observations: list[str] = field(default_factory=list)
    follow_up_topics: list[str] = field(default_factory=list)
    low_priority_summary: str = ""
