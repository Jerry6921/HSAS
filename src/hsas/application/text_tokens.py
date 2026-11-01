"""Shared tokenization for deterministic course and material search."""

from __future__ import annotations

import re


WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[\u3400-\u9fff]+")
__all__ = ["WORD", "tokenize"]


def tokenize(text: str, *, unique: bool = False) -> list[str]:
    """Tokenize Latin words, numbers and Chinese bigrams.

    Latin tokens are case-folded and one-character non-numeric Latin tokens are
    ignored, preserving the historical material-search behavior. Chinese runs
    expand into overlapping bigrams (including a single-character run).
    ``unique`` retains first occurrence order when callers need the
    course-context ranking semantics.
    """
    tokens: list[str] = []
    for match in WORD.findall(text.casefold()):
        if re.fullmatch(r"[\u3400-\u9fff]+", match):
            tokens.extend(
                match[index : index + 2]
                for index in range(max(len(match) - 1, 1))
            )
        elif len(match) > 1 or match.isdigit():
            tokens.append(match)
    return list(dict.fromkeys(tokens)) if unique else tokens
