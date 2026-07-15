"""Tests for chunking and BM25 retrieval — the deterministic core of RAG."""

from __future__ import annotations

from takehome.services.retrieval import BM25, chunk_document, retrieve, tokenize

LEASE = (
    "--- Page 1 ---\n"
    "1.1 This lease is made between the Landlord and the Tenant.\n\n"
    "1.2 The term of this lease is 10 years commencing on 1 January 2026.\n\n"
    "--- Page 2 ---\n"
    "12.3 The Tenant shall not assign or sublet the premises without the prior "
    "written consent of the Landlord, such consent not to be unreasonably withheld.\n\n"
    "14.1 The annual rent is £250,000 payable quarterly in advance."
)

TITLE_REPORT = (
    "--- Page 1 ---\n"
    "The registered proprietor of the property is Acme Holdings Limited.\n\n"
    "There is a right of way granting access over the northern boundary."
)


def test_tokenize_preserves_clause_numbers() -> None:
    tokens = tokenize("Clause 12.3 and section 14.1 apply.")
    assert "12.3" in tokens
    assert "14.1" in tokens
    assert "clause" in tokens


def test_chunk_document_tracks_pages_and_headings() -> None:
    chunks = chunk_document("doc1", "lease.pdf", LEASE)
    assert chunks, "expected at least one chunk"
    # Every chunk carries the page it came from.
    pages = {c.page for c in chunks}
    assert pages == {1, 2}
    # The clause reference at the start of a passage is captured as a heading.
    headings = {c.heading for c in chunks if c.heading}
    assert any(h and h.startswith(("1.", "12.3", "14.1")) for h in headings)


def test_chunk_document_empty_text() -> None:
    assert chunk_document("doc1", "empty.pdf", None) == []
    assert chunk_document("doc1", "empty.pdf", "") == []


def test_bm25_ranks_relevant_chunk_first() -> None:
    chunks = chunk_document("doc1", "lease.pdf", LEASE)
    ranked = BM25(chunks).top_k("Can the tenant assign or sublet the premises?", k=3)
    assert ranked, "expected a match"
    top = ranked[0].chunk
    assert "assign or sublet" in top.text
    assert top.page == 2
    assert ranked[0].score > 0


def test_retrieve_spans_multiple_documents() -> None:
    docs = [
        ("doc1", "lease.pdf", LEASE),
        ("doc2", "title-report.pdf", TITLE_REPORT),
    ]
    # A question about the registered proprietor should surface the title report,
    # not the lease — retrieval reaches across all documents.
    ranked = retrieve(docs, "Who is the registered proprietor of the property?", k=3)
    assert ranked
    assert ranked[0].chunk.document_id == "doc2"
    assert "registered proprietor" in ranked[0].chunk.text.lower()


def test_retrieve_returns_nothing_for_no_overlap() -> None:
    docs = [("doc1", "lease.pdf", LEASE)]
    ranked = retrieve(docs, "photosynthesis chlorophyll mitochondria", k=3)
    assert ranked == []
