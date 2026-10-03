
from app.retrieval.vector_search import search_chunks

question = "What is the six-part prompt formula?"

results = search_chunks(question, top_k=3)

for result in results:
    print(
        f"{result['document']} | Page {result['page']} | "
        f"Distance {result['distance']:.4f}"
    )