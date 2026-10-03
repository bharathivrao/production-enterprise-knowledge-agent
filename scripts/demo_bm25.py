import re

from rank_bm25 import BM25Okapi


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


documents = [
    "Failed settlement batches move to the dead-letter queue.",
    "Teach unfamiliar subjects using examples and a checkpoint.",
    "Improve an email by removing filler and using active voice.",
]

bm25 = BM25Okapi([tokenize(document) for document in documents])

query = "email filler"
scores = bm25.get_scores(tokenize(query))

for document, score in zip(documents, scores, strict=True):
    print(f"Score: {score:.4f} | {document}")