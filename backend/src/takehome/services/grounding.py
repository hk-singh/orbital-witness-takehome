"""Grounding: turn retrieved passages into a citeable prompt, then verify what
the model did with them.

This is the "trust" half of the feature. Retrieval (see retrieval.py) limits
what the model can see to real passages; grounding here (a) presents those
passages as numbered sources the model must cite with `[S1]`-style markers, and
(b) after generation, checks every marker the model emitted against the sources
we actually provided. A marker pointing at a source that doesn't exist is a
fabricated citation — we drop it and it counts against the answer's confidence.

That verification is the concrete answer to the scariest piece of user feedback
("cited a clause that doesn't exist"): the model is no longer trusted to police
its own citations — deterministic code does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from takehome.services.retrieval import ScoredChunk

# Matches citation markers the model is instructed to emit, e.g. [S1] or [S12].
_MARKER = re.compile(r"\[S(\d+)\]")

GROUNDED_SYSTEM_PROMPT = (
    "You are a meticulous legal document assistant for commercial real estate "
    "lawyers doing due diligence. Accuracy matters more than anything: for these "
    "users, a confident wrong answer is worse than 'I don't know'.\n\n"
    "You will be given numbered SOURCES extracted from the user's uploaded "
    "documents. Follow these rules without exception:\n"
    "- Answer ONLY using information found in the provided sources. Do not rely "
    "on outside knowledge or assumptions.\n"
    "- After each sentence or claim, cite the source(s) it comes from using "
    "markers like [S1] or [S2][S3]. Every factual claim must carry a citation.\n"
    "- Quote or closely paraphrase the source; do not embellish beyond it.\n"
    "- If the sources do not contain the answer, say so plainly (e.g. 'The "
    "uploaded documents don't cover this') and do not guess. It is correct and "
    "valuable to say the documents don't address something.\n"
    "- When a question spans several documents, draw from all relevant sources "
    "and make clear which document each point comes from.\n"
    "- Be concise and precise. Lawyers value accuracy over verbosity."
)


@dataclass(frozen=True)
class Citation:
    """A validated citation, resolved back to a specific document and page."""

    marker: str  # e.g. "S1"
    document_id: str
    filename: str
    page: int
    heading: str | None
    snippet: str


def build_sources_block(scored: list[ScoredChunk]) -> tuple[str, dict[str, ScoredChunk]]:
    """Render retrieved chunks as a numbered SOURCES block and return the mapping
    from marker id ("S1") back to the chunk, for later citation resolution.
    """
    if not scored:
        return "", {}

    lines: list[str] = ["SOURCES:"]
    mapping: dict[str, ScoredChunk] = {}
    for i, sc in enumerate(scored, start=1):
        marker = f"S{i}"
        mapping[marker] = sc
        loc = f"{sc.chunk.filename}, page {sc.chunk.page}"
        if sc.chunk.heading:
            loc += f", clause {sc.chunk.heading}"
        lines.append(f"[{marker}] ({loc})\n{sc.chunk.text}")
    return "\n\n".join(lines), mapping


def build_grounded_prompt(
    user_message: str,
    sources_block: str,
    conversation_history: list[dict[str, str]],
) -> str:
    """Assemble the user-turn prompt: sources, prior turns, then the question."""
    parts: list[str] = []
    if sources_block:
        parts.append(sources_block)
    else:
        parts.append(
            "SOURCES: (none — no documents have been uploaded to this "
            "conversation yet, or none matched the question)."
        )

    if conversation_history:
        parts.append("PREVIOUS CONVERSATION:")
        for msg in conversation_history:
            role = msg["role"]
            if role == "user":
                parts.append(f"User: {msg['content']}")
            elif role == "assistant":
                # Strip citation markers from history so they don't confuse the
                # model into reusing stale source numbers from a prior turn.
                parts.append(f"Assistant: {_MARKER.sub('', msg['content'])}")

    parts.append(f"QUESTION: {user_message}")
    return "\n\n".join(parts)


def extract_markers(text: str) -> list[str]:
    """Return citation marker ids present in the text, in first-seen order."""
    seen: list[str] = []
    for match in _MARKER.finditer(text):
        marker = f"S{match.group(1)}"
        if marker not in seen:
            seen.append(marker)
    return seen


def resolve_citations(
    response_text: str, mapping: dict[str, ScoredChunk]
) -> tuple[list[Citation], list[str]]:
    """Split the markers the model emitted into valid citations and fabricated ones.

    A marker is valid only if it refers to a source we actually provided. Anything
    else (e.g. the model writing [S9] when only S1–S6 were given) is a fabricated
    citation and is returned separately so it can be flagged and stripped.
    """
    valid: list[Citation] = []
    fabricated: list[str] = []
    for marker in extract_markers(response_text):
        sc = mapping.get(marker)
        if sc is None:
            fabricated.append(marker)
            continue
        chunk = sc.chunk
        snippet = chunk.text if len(chunk.text) <= 320 else chunk.text[:317].rstrip() + "…"
        valid.append(
            Citation(
                marker=marker,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page=chunk.page,
                heading=chunk.heading,
                snippet=snippet,
            )
        )
    return valid, fabricated


def strip_fabricated_markers(response_text: str, fabricated: list[str]) -> str:
    """Remove markers that don't map to a real source so users never see a
    citation they can't click through to."""
    if not fabricated:
        return response_text
    fabricated_set = set(fabricated)

    def _sub(match: re.Match[str]) -> str:
        return "" if f"S{match.group(1)}" in fabricated_set else match.group(0)

    return _MARKER.sub(_sub, response_text)


# Confidence levels, surfaced to the user as a badge on each answer.
CONFIDENCE_GROUNDED = "grounded"  # well-supported by verified citations
CONFIDENCE_PARTIAL = "partial"  # some support, but thin or mixed
CONFIDENCE_UNSUPPORTED = "unsupported"  # nothing verifiable — treat with care


def compute_confidence(
    valid: list[Citation],
    fabricated: list[str],
    scored: list[ScoredChunk],
    has_documents: bool,
) -> str:
    """Derive a confidence level from grounding coverage and retrieval strength.

    The signal is intentionally simple and explainable rather than a black box:
    - no documents / nothing retrieved / no valid citations -> unsupported
    - several verified citations and a strong retrieval match -> grounded
    - anything in between (few citations, weak match, or some fabrication)
      -> partial
    This is what the user sees as the trust badge, and it is exactly the
    'tell me when you're not sure' signal beta users asked for.
    """
    if not has_documents or not scored or not valid:
        return CONFIDENCE_UNSUPPORTED

    top_score = max((s.score for s in scored), default=0.0)
    distinct_sources = {c.marker for c in valid}

    strong_retrieval = top_score >= 4.0
    well_cited = len(distinct_sources) >= 2

    if well_cited and strong_retrieval and not fabricated:
        return CONFIDENCE_GROUNDED
    if not distinct_sources:
        return CONFIDENCE_UNSUPPORTED
    return CONFIDENCE_PARTIAL
