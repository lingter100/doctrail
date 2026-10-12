"""Small BM25 baseline; Korean bigrams are not morphological analysis."""

import math
import re
from collections import Counter
from dataclasses import dataclass


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9]+|[가-힣]+", text.lower()):
        if "가" <= word[0] <= "힣" and len(word) > 1:
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
        else:
            tokens.append(word)
    return tokens


@dataclass(frozen=True)
class Chunk:
    text: str
    page: int | None
    start_offset: int
    end_offset: int
    ordinal: int


def chunk_content(content: str, pages: list[tuple[int, int, int | None]]) -> list[Chunk]:
    """Offsets are codepoint indices; never strip/rewrite a chunk after slicing."""
    chunks: list[Chunk] = []
    for page_start, page_end, page in pages:
        start = page_start
        while start < page_end:
            end = min(start + 1000, page_end)
            if end < page_end:
                boundary = max(
                    content.rfind("\n", start + 500, end), content.rfind(" ", start + 500, end)
                )
                if boundary > start:
                    end = boundary + 1
            if content[start:end].strip():
                chunks.append(Chunk(content[start:end], page, start, end, len(chunks)))
            if end == page_end:
                break
            start = max(start + 1, end - 150)
    return chunks


def rank_chunks(query: str, candidates: list[dict], limit: int = 10) -> list[dict]:
    """Caller MUST pass only currently visible chunks; IDF uses that corpus only."""
    query_terms = set(tokenize(query))
    if not candidates or not query_terms:
        return []
    frequencies = [Counter(tokenize(candidate["text"])) for candidate in candidates]
    lengths = [sum(freq.values()) for freq in frequencies]
    average_length = sum(lengths) / len(lengths) or 1
    document_frequency = Counter(term for freq in frequencies for term in freq)
    scored = []
    for candidate, freq, length in zip(candidates, frequencies, lengths, strict=True):
        score = 0.0
        for term in sorted(query_terms):
            tf = freq[term]
            if not tf:
                continue
            df = document_frequency[term]
            idf = math.log(1 + (len(candidates) - df + 0.5) / (df + 0.5))
            score += idf * (tf * 2.5) / (tf + 1.5 * (0.25 + 0.75 * length / average_length))
        if score > 0:
            scored.append({**candidate, "score": round(score, 8)})
    return sorted(
        scored,
        key=lambda row: (
            -row["score"],
            row.get("filename", ""),
            row.get("title", ""),
            row.get("start_offset", 0),
            row["text"],
            row["chunk_id"],
        ),
    )[:limit]
