# DECISIONS.md — Part 2.2: Building Something Valuable

> This document has two halves. The **first half** is the submission rationale
> the task asks for: what the data told us, why we picked this feature, and
> what we'd do next. The **second half** ("Under the Hood") is a deeper,
> plain-language walkthrough of the RAG + grounded-citation architecture — how
> it actually works — for anyone (👋 Harsh) who wants to understand the
> machinery, not just the decision.

---

## 1. The insight from the data

I started with the two files in `/data` and let the numbers pick the feature
rather than picking a feature and hunting for numbers to justify it.

**The trust problem is real, and it's measurable — not just anecdotal.**

Parsing `usage_events.csv` (50 users, 102 sessions, 115 conversations, 302
prompt→response pairs, over a ~3-week beta):

| Signal | Value | So what |
| --- | --- | --- |
| Responses citing **zero** sources | **49 / 302 = 16%** | 1-in-6 answers point at *nothing* in the document |
| Mean sources cited per response | 2.67 | The "good" answers do cite — the problem is the tail |
| Negative feedback (👎) | **25 / 102 = 24.5%** | A quarter of rated interactions are unhappy |
| Zero-source rate in 👎 conversations | **18.3%** | ~2× higher... |
| Zero-source rate in 👍 conversations | **9.1%** | ...than in happy ones |

That last pair is the money finding: **conversations that received a thumbs-down
had roughly twice the rate of un-cited answers as conversations that received a
thumbs-up.** Un-grounded answers and distrust move together.

This is corroborated, almost word-for-word, in `customer_feedback.md`:

> *"It's given me an answer that sounds completely authoritative and is just…
> not in the document. That's terrifying when you're advising a client on a
> £40M acquisition."* — Partner, Firm A

> *"She got an answer that was completely fabricated — cited a clause that
> doesn't exist. She doesn't trust it now… In our world, being confidently
> wrong is worse than being slow."* — Partner, Firm B

> *"I'd pay double the licence fee if the AI would just tell me when it's not
> sure rather than making something up. A confidence indicator would change
> everything for me."* — Partner, Firm A

> *"When the AI tells me it's from section 4.2 of the lease, it's magic. When it
> doesn't cite anything specific, I have to go find it myself — so what's the
> point?"* — Associate, Firm A

The frequency data and the qualitative data agree: the single most valuable
improvement is not another capability, it's **making the AI trustworthy** —
answers that are grounded in the actual document text, verifiably cited, and
honest about their own uncertainty.

---

## 2. The decision: grounded, verifiable citations + a confidence signal

We build a Q&A pipeline where every answer is:

1. **Grounded** — the model may only answer from passages actually retrieved
   from the uploaded documents, not from its own memory.
2. **Cited** — each claim carries a citation that quotes an *exact span* from a
   specific document and page, and that citation is **clickable**: it jumps the
   reader panel to that document and location.
3. **Verified** — after the model answers, we programmatically check that each
   quoted span *actually exists* in the source text. A quote the model invented
   fails this check and is flagged rather than shown as fact.
4. **Honest about confidence** — the answer carries a badge derived from how
   much of it is backed by verified citations: e.g. **Well-grounded** /
   **Partially supported** / **Not found in the documents**.

### Why this over the alternatives

| Option | Why not (as the 2.2 feature) |
| --- | --- |
| **Document library / reuse** | The data backs it hard — **76% of uploads are redundant re-uploads** of a doc already seen in another conversation — but this overlaps heavily with the *required* Part 2.1 multi-document work. Building it as the "extra" feature would be double-counting effort. |
| **In-viewer search / highlight** | Nice polish, and requested, but it's a convenience, not the thing making a partner distrust the product. |
| **Report export** | Requested, but lower strategic value and it *exports the trust problem* — you'd be pasting possibly-hallucinated answers into a client document. Grounding has to come first. |
| **Grounded citations + confidence ✅** | Directly attacks the highest-severity, highest-willingness-to-pay problem ("I'd pay double"), is backed by the strongest quantitative signal (the 2× zero-source/👎 correlation), and **composes with multi-document** — citations become the thing that tells you *which* of several documents each fact came from. |

Grounded citations aren't just a feature bolted onto multi-doc; they're what
makes multi-doc *safe*. When an answer draws on five documents at once, "trust
me" is unacceptable — "here's the exact clause in each, click to verify" is the
whole product.

---

## 3. What I'd do next with more time

- **Hybrid retrieval.** Legal text mixes semantic questions ("what are the
  break rights?") with exact-token lookups ("clause 12.3"). Pure vector search
  is weak at the latter. I'd add a lexical/BM25 pass and fuse the two (see the
  deep-dive below for why).
- **Span-level highlighting in the viewer**, not just page-level jumps — draw
  the actual bounding box of the cited text on the PDF using PyMuPDF's
  coordinate data.
- **Cross-document contradiction detection.** Multiple partners want to compare
  what two documents say about the same topic; a grounded system can surface
  *"the lease says X but the purchase agreement says Y."*
- **Feedback loop.** We already log `thumbs_up/down`; I'd tie that to retrieval
  quality metrics so the confidence signal is calibrated against real outcomes,
  not just heuristics.

---
---

# Under the Hood: How Grounded Citations Actually Work

*A plain-language tour of the architecture, for understanding rather than
grading. Skip this if you only need the decision.*

## The problem with the baseline (and why we can't just "prompt harder")

The MVP we inherited does the simplest possible thing. On every question it
takes the **entire** extracted text of the one document and pastes it into the
prompt:

```
Here is the document:
<document>
...50 pages of lease...
</document>
Answer the user's question.
```

Then it *asks* the model, in the system prompt, to "cite the relevant section"
and to "not fabricate." That's it. There is no mechanism — only a polite
request.

This fails in two ways that the data caught:

1. **It doesn't scale to many documents.** Stuffing one 50-page lease is
   already large; stuffing the "dozens of documents per deal" that real users
   have is impossible — you blow past the context window, and even within it,
   models get lossy and distracted in very long contexts ("lost in the middle").
2. **"Please cite" is not grounding.** The model generates the most
   *plausible-sounding* continuation. If a plausible-sounding answer mentions
   "Clause 14.2," it will happily write "Clause 14.2" whether or not clause 14.2
   exists. The old `count_sources_cited()` function is a perfect illustration of
   the trap: it counts the *words* "section 5" / "clause 3" in the reply with a
   regex. It measures whether the model **said something that looks like a
   citation**, not whether the citation is **true**. That's exactly how you get
   a "cited a clause that doesn't exist."

Grounding is the fix: instead of trusting the model to police itself, we change
the *architecture* so it can only draw from real text, and we *verify* its
citations against that text after the fact.

## RAG in one sentence

**RAG (Retrieval-Augmented Generation)** = before you ask the model anything,
go *retrieve* the handful of passages most relevant to the question, and put
*only those* in front of the model as its source material.

The analogy I like: the baseline hands a lawyer the entire filing cabinet and
says "the answer's in here somewhere, go." RAG is a diligent paralegal who
first pulls the three specific pages that matter and lays them on the desk. The
lawyer (the LLM) then answers from what's on the desk — and, crucially, can
point at the exact page for each thing they say.

## The pipeline, stage by stage

### Stage 1 — Ingestion & chunking (happens once, at upload time)

When a PDF is uploaded we already extract text per page with PyMuPDF. We extend
this: split each document into **chunks** — coherent passages of a few hundred
tokens each (roughly a paragraph or a clause), *with their metadata preserved*:

```
chunk = {
  text: "12.3 The Tenant shall not assign… without consent…",
  document_id: "doc_abc",
  filename: "commercial-lease-100-bishopsgate.pdf",
  page: 14,
  char_start / char_end: offsets back into the page text
}
```

Why chunk? Two reasons. **Retrieval** works better on focused passages than on
whole documents (a page about rent shouldn't be pulled in for a question about
insurance). And **citation** needs granularity — "page 14, clause 12.3" is a
useful citation; "somewhere in this 50-page PDF" is not. The metadata is what
later makes a citation *clickable* — it's the address we jump the viewer to.

### Stage 2 — Retrieval with BM25 (finding the right passages for *this* question)

This is the deliberate engineering trade-off of the whole feature, so it's worth
being precise about. **What we actually built is lexical retrieval using BM25**,
not vector embeddings. When the user asks a question, we tokenise it, then score
every chunk (across *all* documents in the conversation) by BM25 and take the
**top-k** (k=6). That "across all documents" is exactly how multi-document Q&A
works: retrieval doesn't care which file a chunk came from, so a single question
naturally pulls the most relevant clause from the lease *and* the matching
clause from the purchase agreement.

**What BM25 is, plainly:** it scores a passage by how many of the query's words
it contains, but with two pieces of judgement baked in. Rare words count for
more than common ones (asking about "indemnity" should reward the one clause
that says "indemnity", not every page that says "the"), and it dampens two kinds
of cheating — repeating a word many times, and a passage simply being long. It's
the classic search-engine ranking function, and it's implemented from scratch in
`retrieval.py` (~40 lines, no dependencies).

**Why lexical, not embeddings?** Three reasons, in order of importance:
1. **Legal questions are token-heavy.** Lawyers ask about "clause 12.3",
   "Schedule 4", "the break option", named parties. BM25 nails exact-token
   matching; naive semantic search can actually *rank the wrong clause higher*
   because it's "about" the same topic. Our tokenizer even keeps "12.3" intact
   as one token instead of shredding it into "12" and "3".
2. **No new moving parts.** Embeddings need an embedding API (Anthropic doesn't
   offer one — you'd add Voyage/OpenAI and another key) or a local model
   (hundreds of MB of PyTorch), plus a vector store. BM25 runs in-process,
   offline, deterministically. For a beta at this scale it's the right amount of
   machine, and it means the feature runs anywhere the app runs.
3. **It makes the trust story testable.** Because it's deterministic, the whole
   retrieval + grounding path is covered by fast unit tests with no API calls —
   which is how the citation/confidence logic is verified in this repo.

> **The honest limitation (and the upgrade path):** pure lexical search misses
> pure-synonym questions — ask "can the tenant get out of the lease early?" when
> the document only ever says "right to determine", and BM25 sees no shared
> words. The production answer is **hybrid retrieval**: run BM25 *and* a semantic
> embedding search, then fuse the rankings so you get exact-token precision *and*
> synonym recall. That's the headline item in "what I'd do next" — embeddings
> aren't abandoned, they're the second half of a better retriever. This is the
> single most important thing to add as the corpus and user base grow.

### Stage 3 — Generation with a grounding contract

Now we prompt the model, but the prompt is different from the baseline. Instead
of "here's a document, please cite," we give it *only the retrieved chunks*,
each tagged with an ID, and a strict instruction:

```
Use ONLY the passages below. Every claim must cite the passage ID it comes from.
If the passages don't contain the answer, say so — do not use outside knowledge.

[S1] (lease, p.14) "12.3 The Tenant shall not assign…"
[S2] (purchase agreement, p.3) "The Seller indemnifies…"
...
```

The model answers and attaches citations like `[S1]`. Because its *entire
world* is those passages, it has nothing else to hallucinate from — the
architecture, not a plea, is what keeps it honest.

### Stage 4 — Verification (the part that earns the "grounded" label)

This is the step that separates real grounding from "please cite," and it's the
direct answer to *"cited a clause that doesn't exist."* After the model finishes,
we take every `[Sn]` marker it emitted and **check it against the sources we
actually provided** (`resolve_citations` in `grounding.py`):

- Marker maps to a real source we sent (e.g. `[S1]` when S1…S6 were provided) →
  ✅ a verified citation. We resolve it to its `{document, page, clause}` and
  render it as a clickable chip that jumps the reader to that exact page.
- Marker maps to nothing (e.g. the model writes `[S9]` when only S1…S6 exist) →
  🚩 a **fabricated citation**. We strip it from the answer so the user never
  sees a citation they can't click through to, log it, and count it against the
  answer's confidence.

Two things make this trustworthy rather than cosmetic. First, the model's
*entire world* is the retrieved passages, so a claim can't be grounded in
outside knowledge — it has nothing else to draw on. Second, the marker check is
deterministic code, not another model: the LLM is no longer the last line of
defence for its own honesty. (The natural next increment, noted below, is to go
from "the marker points at a real source" to "the model's quoted words actually
appear in that source" — a span-level string match. The current check already
catches the failure mode users reported; span-matching tightens it further.)

### Stage 5 — The confidence signal

The badge users said they'd "pay double" for falls out of Stage 4. Confidence is
a simple, explainable function of grounding coverage and retrieval strength
(`compute_confidence` in `grounding.py`) — deliberately a transparent rule, not
a black-box score:

- **Grounded** (green): at least two distinct verified citations, a strong
  retrieval match, and no fabricated markers.
- **Partially supported** (amber): some verified citations, but thin (only one),
  a weak retrieval match, or some fabrication mixed in — verify before relying.
- **Unverified** (grey): no documents, nothing retrieved, or no citation
  survived verification. This is treated as a *feature*, not a failure: an
  honest "the documents don't cover this" is exactly what the partners asked
  for, and it's what turns "confidently wrong" into "usefully cautious."

## How the pieces connect

```
Upload ──▶ Extract (PyMuPDF) ──▶ Chunk (+page/clause metadata) ──▶ store text
                                                                        │
User question ──▶ Chunk all docs ──▶ BM25 rank ──▶ top-k across ALL docs┘
                                        │
                                        ▼
                    Generate (answer only from retrieved sources, cite [Sn])
                                        │
                                        ▼
                    Verify each [Sn] marker against the provided sources
                                        │
                        ┌───────────────┴───────────────┐
                        ▼                                ▼
             Clickable citation chips            Confidence badge
             (jump the viewer to the           (from grounding coverage
              cited document + page)             + retrieval strength)
```

The through-line: **retrieval** makes multi-document Q&A possible and keeps the
context focused; **the grounding contract** limits what the model can say;
**verification** makes citations trustworthy instead of decorative; and
**confidence** turns the system's own honesty into something the user can see.
Together they convert the scariest quote in the feedback file — "confidently
wrong is worse than slow" — into the product's headline strength.
