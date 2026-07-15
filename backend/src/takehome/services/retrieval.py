"""Retrieval for grounded Q&A.

The baseline stuffed a whole document into the prompt and *asked* the model to
cite. That doesn't scale to many documents and, more importantly, gives the
model nothing to be grounded against — it can invent a clause and no code ever
checks. This module is the "retrieval" half of retrieval-augmented generation:
it splits documents into passages and, for a given question, returns only the
most relevant passages across *all* documents in a conversation. Those passages
become the model's entire source material and the anchors for citations.

Retrieval here is lexical (BM25), not vector-embedding based. That is a
deliberate trade-off — see DECISIONS.md. In short: legal questions lean heavily
on exact tokens ("clause 12.3", "Schedule 4", "break option"), BM25 handles
those precisely, and it needs no embedding API key or vector database, so the
feature runs anywhere the app runs. Semantic embeddings are the natural upgrade.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

# Matches the "--- Page N ---" markers that document extraction writes so we can
# recover per-page boundaries (and therefore page-accurate citations).
_PAGE_MARKER = re.compile(r"---\s*Page\s+(\d+)\s*---")

# A token is a run of letters/digits, optionally with dotted or hyphenated
# numeric suffixes so clause references like "12.3" or "b-1" survive as single
# tokens instead of being shredded into "12" and "3".
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")

# Detects a leading clause/section reference at the start of a passage, e.g.
# "12.3 The Tenant shall..." or "SECTION 5." — used as a human-friendly label.
_HEADING = re.compile(
    r"^\s*(?:(?:section|clause|schedule|part|paragraph)\s+)?(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

# Target passage size in characters. Small enough that a citation points at
# something specific, large enough to keep a clause intact.
_TARGET_CHARS = 900
_MAX_CHARS = 1400


@dataclass(frozen=True)
class Chunk:
    """A retrievable passage from a document, with enough metadata to cite it."""

    document_id: str
    filename: str
    page: int
    text: str
    heading: str | None


@dataclass(frozen=True)
class ScoredChunk:
    """A chunk plus its relevance score for a particular query."""

    chunk: Chunk
    score: float


def tokenize(text: str) -> list[str]:
    """Lowercase and split text into retrieval tokens."""
    return _TOKEN.findall(text.lower())


def _split_pages(extracted_text: str) -> list[tuple[int, str]]:
    """Recover (page_number, page_text) pairs from extracted document text.

    Falls back to a single page 1 if no page markers are present (e.g. text that
    was extracted without them).
    """
    matches = list(_PAGE_MARKER.finditer(extracted_text))
    if not matches:
        stripped = extracted_text.strip()
        return [(1, stripped)] if stripped else []

    pages: list[tuple[int, str]] = []
    for i, match in enumerate(matches):
        page_num = int(match.group(1))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(extracted_text)
        page_text = extracted_text[start:end].strip()
        if page_text:
            pages.append((page_num, page_text))
    return pages


def _heading_for(text: str) -> str | None:
    match = _HEADING.match(text)
    return match.group(1) if match else None


def chunk_document(document_id: str, filename: str, extracted_text: str | None) -> list[Chunk]:
    """Split one document's extracted text into page-aware passages.

    Paragraphs (separated by blank lines) are packed together up to a target
    size so a chunk is usually a coherent clause or two, never split mid-clause
    unless a single paragraph is itself enormous.
    """
    if not extracted_text:
        return []

    chunks: list[Chunk] = []
    for page_num, page_text in _split_pages(extracted_text):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", page_text) if p.strip()]
        buffer = ""
        for para in paragraphs:
            # A single oversized paragraph is emitted on its own (hard-split if
            # truly huge) rather than dragging unrelated text along with it.
            if len(para) > _MAX_CHARS:
                if buffer:
                    chunks.append(_make_chunk(document_id, filename, page_num, buffer))
                    buffer = ""
                for start in range(0, len(para), _MAX_CHARS):
                    chunks.append(
                        _make_chunk(document_id, filename, page_num, para[start : start + _MAX_CHARS])
                    )
                continue

            candidate = f"{buffer}\n\n{para}" if buffer else para
            if len(candidate) > _TARGET_CHARS and buffer:
                chunks.append(_make_chunk(document_id, filename, page_num, buffer))
                buffer = para
            else:
                buffer = candidate

        if buffer:
            chunks.append(_make_chunk(document_id, filename, page_num, buffer))

    return chunks


def _make_chunk(document_id: str, filename: str, page: int, text: str) -> Chunk:
    text = text.strip()
    return Chunk(
        document_id=document_id,
        filename=filename,
        page=page,
        text=text,
        heading=_heading_for(text),
    )


class BM25:
    """A compact BM25 ranker over an in-memory set of chunks.

    BM25 scores a passage by how many query terms it contains, weighting rare
    terms more (idf) and dampening the reward for repeating a term or for a
    passage simply being long. It's the workhorse of classical search and,
    unlike a naive keyword count, it doesn't let a long page drown out a short,
    on-point clause.
    """

    def __init__(self, chunks: list[Chunk], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self._doc_tokens = [tokenize(c.text) for c in chunks]
        self._doc_freqs = [Counter(toks) for toks in self._doc_tokens]
        self._doc_len = [len(toks) for toks in self._doc_tokens]
        self._avg_len = (sum(self._doc_len) / len(self._doc_len)) if self._doc_len else 0.0

        # Document frequency: in how many chunks does each term appear?
        df: Counter[str] = Counter()
        for freqs in self._doc_freqs:
            df.update(freqs.keys())

        n = len(chunks)
        self._idf: dict[str, float] = {}
        for term, freq in df.items():
            # Standard BM25 idf with the +1 smoothing that keeps it non-negative.
            self._idf[term] = math.log(1 + (n - freq + 0.5) / (freq + 0.5))

    def _score(self, query_terms: list[str], index: int) -> float:
        if self._avg_len == 0:
            return 0.0
        freqs = self._doc_freqs[index]
        length = self._doc_len[index]
        score = 0.0
        for term in query_terms:
            tf = freqs.get(term, 0)
            if tf == 0:
                continue
            idf = self._idf.get(term, 0.0)
            denom = tf + self.k1 * (1 - self.b + self.b * length / self._avg_len)
            score += idf * (tf * (self.k1 + 1)) / denom
        return score

    def top_k(self, query: str, k: int) -> list[ScoredChunk]:
        query_terms = tokenize(query)
        if not query_terms or not self.chunks:
            return []
        scored = [
            ScoredChunk(chunk=self.chunks[i], score=self._score(query_terms, i))
            for i in range(len(self.chunks))
        ]
        scored = [s for s in scored if s.score > 0]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]


def retrieve(documents: list[tuple[str, str, str | None]], query: str, k: int = 6) -> list[ScoredChunk]:
    """Chunk every document and return the top-k passages for the query.

    `documents` is a list of (document_id, filename, extracted_text). Chunking is
    done per call because at beta scale (a handful of documents per conversation)
    it's fast and keeps citations always in sync with the stored text. Persisting
    chunks + embeddings is the production upgrade noted in DECISIONS.md.
    """
    all_chunks: list[Chunk] = []
    for document_id, filename, extracted_text in documents:
        all_chunks.extend(chunk_document(document_id, filename, extracted_text))
    if not all_chunks:
        return []
    return BM25(all_chunks).top_k(query, k)
