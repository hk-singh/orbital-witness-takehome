"""Tests for grounding: source formatting, citation verification, confidence."""

from __future__ import annotations

from takehome.services.grounding import (
    CONFIDENCE_GROUNDED,
    CONFIDENCE_PARTIAL,
    CONFIDENCE_UNSUPPORTED,
    build_sources_block,
    compute_confidence,
    extract_markers,
    resolve_citations,
    strip_fabricated_markers,
)
from takehome.services.retrieval import Chunk, ScoredChunk


def _scored(marker_text: str, *, doc: str, page: int, score: float, heading: str | None = None) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(
            document_id=doc,
            filename=f"{doc}.pdf",
            page=page,
            text=marker_text,
            heading=heading,
        ),
        score=score,
    )


def _sample_sources() -> list[ScoredChunk]:
    return [
        _scored("The Tenant shall not assign or sublet.", doc="d1", page=2, score=6.0, heading="12.3"),
        _scored("The annual rent is £250,000.", doc="d1", page=2, score=5.0, heading="14.1"),
        _scored("Right of way over the northern boundary.", doc="d2", page=1, score=4.5),
    ]


def test_build_sources_block_numbers_and_maps() -> None:
    block, mapping = build_sources_block(_sample_sources())
    assert "[S1]" in block and "[S2]" in block and "[S3]" in block
    assert "page 2" in block and "clause 12.3" in block
    assert set(mapping.keys()) == {"S1", "S2", "S3"}
    assert mapping["S1"].chunk.document_id == "d1"


def test_build_sources_block_empty() -> None:
    block, mapping = build_sources_block([])
    assert block == ""
    assert mapping == {}


def test_extract_markers_dedupes_in_order() -> None:
    assert extract_markers("Foo [S2] bar [S1] baz [S2].") == ["S2", "S1"]


def test_resolve_citations_splits_valid_and_fabricated() -> None:
    _, mapping = build_sources_block(_sample_sources())
    text = "Assignment is restricted [S1]. Rent is set [S2]. Something invented [S9]."
    valid, fabricated = resolve_citations(text, mapping)
    assert {c.marker for c in valid} == {"S1", "S2"}
    assert fabricated == ["S9"]
    # Valid citations resolve to concrete, clickable locations.
    s1 = next(c for c in valid if c.marker == "S1")
    assert s1.document_id == "d1"
    assert s1.page == 2
    assert s1.heading == "12.3"
    assert s1.snippet


def test_strip_fabricated_markers_removes_only_invalid() -> None:
    text = "Real [S1] and fake [S9]."
    assert strip_fabricated_markers(text, ["S9"]) == "Real [S1] and fake ."
    # Nothing to strip leaves text untouched.
    assert strip_fabricated_markers(text, []) == text


def test_confidence_grounded_when_well_cited_and_strong() -> None:
    scored = _sample_sources()
    _, mapping = build_sources_block(scored)
    valid, fabricated = resolve_citations("A [S1]. B [S2].", mapping)
    assert (
        compute_confidence(valid, fabricated, scored, has_documents=True)
        == CONFIDENCE_GROUNDED
    )


def test_confidence_partial_when_single_citation() -> None:
    scored = _sample_sources()
    _, mapping = build_sources_block(scored)
    valid, fabricated = resolve_citations("Only one [S1].", mapping)
    assert (
        compute_confidence(valid, fabricated, scored, has_documents=True)
        == CONFIDENCE_PARTIAL
    )


def test_confidence_partial_when_fabrication_present() -> None:
    scored = _sample_sources()
    _, mapping = build_sources_block(scored)
    valid, fabricated = resolve_citations("A [S1]. B [S2]. C [S9].", mapping)
    # Two valid citations but one fabricated -> not fully grounded.
    assert fabricated == ["S9"]
    assert (
        compute_confidence(valid, fabricated, scored, has_documents=True)
        == CONFIDENCE_PARTIAL
    )


def test_confidence_unsupported_without_citations_or_docs() -> None:
    scored = _sample_sources()
    assert (
        compute_confidence([], [], scored, has_documents=True)
        == CONFIDENCE_UNSUPPORTED
    )
    assert (
        compute_confidence([], [], [], has_documents=False)
        == CONFIDENCE_UNSUPPORTED
    )


def test_confidence_weak_retrieval_is_partial() -> None:
    weak = [
        _scored("Some tangentially related text.", doc="d1", page=1, score=1.2),
        _scored("More marginal text.", doc="d1", page=1, score=1.0),
    ]
    _, mapping = build_sources_block(weak)
    valid, fabricated = resolve_citations("A [S1]. B [S2].", mapping)
    # Well-cited but the retrieval match is weak, so we don't claim "grounded".
    assert (
        compute_confidence(valid, fabricated, weak, has_documents=True)
        == CONFIDENCE_PARTIAL
    )
