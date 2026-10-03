import tiktoken

from app.core.config import get_settings


def build_context(results, *, max_tokens=None):
    blocks = []
    sources = {}
    encoding = tiktoken.get_encoding("cl100k_base")
    budget = max_tokens or get_settings().max_context_tokens
    used_tokens = 0

    for index, result in enumerate(results, start=1):
        source_id = f"S{index}"

        source = {
            "document": result["document"],
            "page": result["page"],
        }
        if result.get("section") is not None:
            source["section"] = result["section"]
        location = (
            f"Page: {result['page']}"
            if result.get("page") is not None
            else f"Section: {result.get('section') or 'Document'}"
        )
        block = (
            f"[{source_id}]\n"
            f"Document: {result['document']}\n"
            f"{location}\n"
            f"Evidence:\n{result['content']}"
        )
        block_tokens = encoding.encode(block)
        if blocks and used_tokens + len(block_tokens) > budget:
            break
        if len(block_tokens) > budget:
            block = encoding.decode(block_tokens[:budget])
            block_tokens = block_tokens[:budget]
        blocks.append(block)
        sources[source_id] = source
        used_tokens += len(block_tokens)

    return {
        "context": "\n\n".join(blocks),
        "sources": sources,
        "token_count": used_tokens,
    }
