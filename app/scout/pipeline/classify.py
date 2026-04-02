from __future__ import annotations


CATEGORY_RULES = {
    "研究": ["research", "paper", "benchmark", "evaluation", "arxiv", "model", "llm", "reasoning"],
    "产品": ["launch", "product", "feature", "assistant", "copilot", "api", "release"],
    "开源": ["open source", "open-source", "github", "repository", "repo", "weights", "apache", "mit"],
    "应用": ["agent", "workflow", "automation", "app", "tool", "deployment", "enterprise"],
    "融资/公司动态": ["funding", "acquisition", "startup", "company", "raised", "investment", "partnership"],
    "新闻": ["news", "update", "announced", "announcement"],
}


def classify_items(items: list[dict]) -> list[dict]:
    classified: list[dict] = []
    for item in items:
        detected_category = classify_text(
            " ".join(
                [
                    item.get("title", ""),
                    item.get("summary", ""),
                    item.get("raw_category", ""),
                    item.get("source", ""),
                ]
            )
        )
        classified.append({**item, "category": detected_category})
    return classified


def classify_text(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_RULES.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "其他"
