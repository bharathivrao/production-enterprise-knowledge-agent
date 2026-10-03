def build_context(results):
    blocks = []
    sources = {}

    for index, result in enumerate(results, start=1):
        source_id = f"S{index}"

        source = {
            "document": result["document"],
            "page": result["page"],
        }
        if result.get("section") is not None:
            source["section"] = result["section"]
        sources[source_id] = source

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
        blocks.append(block)

    return {
        "context": "\n\n".join(blocks),
        "sources": sources,
    }
