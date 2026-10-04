"""Conservative credential screening before text reaches embedding or memory."""

import re


_CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,})\b"),
    re.compile(
        r"(?i)\b(?:password|api[_ -]?key|client[_ -]?secret)\s*[:=]\s*"
        r"[\"']?[A-Za-z0-9+/_=-]{16,}"
    ),
)
_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def contains_credential(text: str) -> bool:
    return any(pattern.search(text) for pattern in _CREDENTIAL_PATTERNS)


def contains_high_risk_pii(text: str) -> bool:
    if _SSN.search(text):
        return True
    for match in _CARD_CANDIDATE.finditer(text):
        digits = [int(value) for value in match.group() if value.isdigit()]
        if not 13 <= len(digits) <= 19:
            continue
        total = 0
        for index, digit in enumerate(reversed(digits)):
            if index % 2:
                digit *= 2
                if digit > 9:
                    digit -= 9
            total += digit
        if total % 10 == 0:
            return True
    return False
