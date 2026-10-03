import re


def validate_citations(answer, sources):
    cited_ids = set(re.findall(r"\[(S\d+)\]", answer))
    unknown_ids = cited_ids - set(sources)

    if not cited_ids and answer.strip() != "The available documents do not contain enough information.":
        raise CitationValidationError("Answer must contain a source citation")
    
    if unknown_ids:
        raise CitationValidationError(
            f"Unknown citation IDs: {sorted(unknown_ids)}"
        )

    return [
        {"source_id": source_id, **sources[source_id]}
        for source_id in sorted(
            cited_ids,
            key=lambda value: int(value[1:]),
        )
    ]

class CitationValidationError(ValueError):
    """Raised when generated citations fail validation."""