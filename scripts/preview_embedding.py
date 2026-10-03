import ollama

from app.ingestion.pipeline import prepare_document
from app.core.config import get_settings

settings = get_settings()
chunks = prepare_document("data/raw/sample.pdf")

response = ollama.embed(
    model=settings.embedding_model,
    input=chunks[0]["content"],
    truncate=False,
)

embedding = response["embeddings"][0]

print("Dimensions:", len(embedding))
print("First five values:", embedding[:5])
print("Tokens processed:", response["prompt_eval_count"])