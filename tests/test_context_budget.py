import tiktoken

from app.generation.context_builder import build_context


def test_context_budget_excludes_sources_not_sent_to_model():
    results = [
        {"document": "a.md", "page": None, "section": "A", "content": "short"},
        {"document": "b.md", "page": None, "section": "B", "content": "x " * 200},
    ]
    first_block = build_context(results[:1], max_tokens=1000)["context"]
    first_tokens = len(tiktoken.get_encoding("cl100k_base").encode(first_block))
    evidence = build_context(results, max_tokens=first_tokens + 1)
    assert set(evidence["sources"]) == {"S1"}
    assert "b.md" not in evidence["context"]
