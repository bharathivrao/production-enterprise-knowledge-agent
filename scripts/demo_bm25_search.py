from app.retrieval.bm25 import search_bm25

results = search_bm25("settlement dead-letter queue", top_k=3)

for result in results:
    print(
        f"{result['document']} | Page {result['page']} | "
        f"BM25: {result['bm25_score']:.4f}"
    )