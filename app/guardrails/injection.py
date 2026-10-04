"""Reject high-confidence document-borne instruction attacks before indexing."""

import re


_DIRECTIVES = (
    re.compile(r"(?i)\bignore (?:all )?(?:previous|prior|system) instructions\b"),
    re.compile(r"(?i)\breveal (?:the )?(?:system|developer) prompt\b"),
    re.compile(r"(?i)\b(?:override|bypass) (?:the )?(?:security|access|authorization) (?:policy|checks?)\b"),
    re.compile(r"<\|im_start\|>\s*system", re.I),
)


def contains_embedded_instruction(text: str) -> bool:
    return any(pattern.search(text) for pattern in _DIRECTIVES)
