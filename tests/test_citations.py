from app.generation.citations import validate_citations

import pytest

from app.generation.citations import CitationValidationError

def test_valid_citation_resolves_source():
    sources = {
        "S1": {"document": "sample.pdf", "page": 1},
    }

    result = validate_citations("The formula has six parts [S1].", sources)

    assert result == [
        {
            "source_id": "S1",
            "document": "sample.pdf",
            "page": 1,
        }
    ]

def test_unknown_citation_is_rejected():
    with pytest.raises(CitationValidationError):
        validate_citations("Claim [S99].", {})

def test_insufficient_information_returns_empty():
    
    sources = {
    "S1": {"document": "sample.pdf", "page": 1},
    }

    result = validate_citations(
        "The available documents do not contain enough information.",
        sources,
    )

    assert result == []