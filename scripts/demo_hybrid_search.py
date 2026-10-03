from app.retrieval.hybrid import search_hybrid

results = search_hybrid(
    "How can I get an AI to help me study without rushing ahead?",
    top_k=3,
)

for result in results:
    print(
        f"{result['document']} | Page {result['page']} | "
        f"RRF: {result['rrf_score']:.6f}"
    )