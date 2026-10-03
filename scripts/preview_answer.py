from app.generation.citations import validate_citations
from app.generation.context_builder import build_context
from app.generation.generator import generate_answer
from app.retrieval.vector_search import search_chunks

question = "What is the six-part prompt formula?"
results = search_chunks(question, top_k=3)
evidence = build_context(results)

answer = generate_answer(question, evidence["context"])
citations = validate_citations(answer=answer, sources=evidence["sources"])

print(answer)
print("\nValidated citations:", citations)