
from app.ingestion.pipeline import ingest_pdf

result = ingest_pdf("data/raw/sample.pdf")

print(result)
