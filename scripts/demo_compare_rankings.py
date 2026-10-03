from app.retrieval.bm25 import search_bm25, tokenize
from app.retrieval.vector_search import search_chunks

query = "How can I get an AI to help me study without rushing ahead?"
query_words = set(tokenize(query))

print("VECTOR")
for result in search_chunks(query, top_k=6):
    print(
        f"{result['document']} | Page {result['page']} | "
        f"Distance: {result['distance']:.4f}"
    )

print("\nBM25")
for result in search_bm25(query, top_k=6):
    matched_words = sorted(
        query_words & set(tokenize(result["content"]))
    )
    print(
        f"{result['document']} | Page {result['page']} | "
        f"BM25: {result['bm25_score']:.4f} | "
        f"Matching words: {matched_words}"
    )