from app.db.repository import load_search_chunks

chunks = load_search_chunks()

print(f"Loaded chunks: {len(chunks)}")

for chunk in chunks[:3]:
    print(
        f"{chunk['chunk_id']} | "
        f"{chunk['document']} | Page {chunk['page']}"
    )