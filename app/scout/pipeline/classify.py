from __future__ import annotations


CATEGORY_RULES = {
    "模型": ["model", "llm", "gpt", "reasoning", "multimodal", "qwen", "gemini", "claude"],
    "产品": ["launch", "product", "feature", "assistant", "workspace", "copilot", "api"],
    "开源": ["open source", "github", "repository", "repo", "weights", "apache", "mit"],
    "研究": ["research", "paper", "benchmark", "evaluation", "arxiv"],
    "应用": ["agent", "workflow", "automation", "app", "tool"],
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
