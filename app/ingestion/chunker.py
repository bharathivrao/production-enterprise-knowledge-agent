import tiktoken


def chunk_pages(pages, chunk_size=500, overlap=50):
    """Chunk ordered source units while retaining page/section provenance."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")

    chunks = []
    step = chunk_size - overlap
    encoding = tiktoken.get_encoding("cl100k_base")
    for source in pages:
        token_ids = encoding.encode(source["content"])
        for start in range(0, len(token_ids), step):
            chunk_token_ids = token_ids[start : start + chunk_size]
            chunks.append({
                "filename": source["filename"],
                "page": source.get("page"),
                "section": source.get("section"),
                "chunk_index": len(chunks),
                "content": encoding.decode(chunk_token_ids),
            })
            if start + chunk_size >= len(token_ids):
                break
    return chunks
