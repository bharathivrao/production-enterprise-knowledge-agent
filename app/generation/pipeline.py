from app.generation.citations import validate_citations
from app.generation.context_builder import build_context
from app.generation.generator import generate_answer
from app.retrieval.vector_search import search_chunks
from app.generation.output import extract_final_answer

def answer_question(question, top_k=5):
    results = search_chunks(question, top_k=top_k)

    if not results:
        return {
            "answer": "The available documents do not contain enough information.",
            "citations": [],
        }

    evidence = build_context(results)

    raw_answer = generate_answer(question, evidence["context"])
    answer = extract_final_answer(raw_answer)
    citations = validate_citations(answer, evidence["sources"])

    return {
        "answer": answer,
        "citations": citations,
    }