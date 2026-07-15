# FORHARSH.md — The whole project, in plain language

Hey Harsh 👋 — this is the "explain it like we're sitting together with a coffee"
document. By the end you should understand what this app is, every meaningful
piece of how it's built, *why* we made each call, the mistakes we dodged (and
the ones we'd hit at scale), and how you'd grow it from a beta toy into
something that serves thousands of lawyers. Read it top to bottom; it builds.

If `DECISIONS.md` is the "why this feature" essay for the assessor, this is the
"teach me the engineering" companion for you.

---

## 1. The one-paragraph story

Orbital gave us a working-but-limited app: commercial real estate lawyers upload
a legal PDF and ask an AI questions about it. It's a ChatGPT-style interface with
a document reader on the right. The catch: **each conversation could hold exactly
one document, and the AI would happily make things up** — cite a clause that
doesn't exist, sound totally confident, and quietly destroy a lawyer's trust. Our
job was to (a) let a conversation hold *many* documents and answer across all of
them, and (b) pick one high-value improvement from real usage data and build it.
We picked **trust**: grounded answers that cite the exact source and tell you how
confident they are. This doc explains all of it.

---

## 2. The lay of the land (architecture in one picture)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser (React + Vite + Tailwind + shadcn/Radix)                    │
│                                                                       │
│   ChatSidebar   │        ChatWindow            │   DocumentViewer     │
│  (conversations)│  (messages, citations,       │  (PDF reader, doc    │
│                 │   confidence, chat input)    │   switcher, jump-to) │
└───────┬─────────┴──────────────┬───────────────┴──────────┬──────────┘
        │  fetch / SSE stream     │                          │  PDF bytes
        ▼                         ▼                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FastAPI backend (Python 3.12)                                        │
│                                                                       │
│  routers/            services/                    db/                 │
│   conversations   →   conversation.py          →  models.py (ORM)     │
│   documents       →   document.py (upload,PyMuPDF)                     │
│   messages        →   retrieval.py (chunk+BM25)   session.py          │
│                       grounding.py (cite+confidence)                  │
│                       llm.py (PydanticAI → Claude)                    │
└───────────────────────────────────┬───────────────────────────────────┘
                                     ▼
                        PostgreSQL  +  Anthropic API (Claude Haiku)
```

Everything runs in Docker Compose: Postgres, the FastAPI backend (port 8000),
and the Vite dev server (port 5173). Alembic runs DB migrations automatically
when the backend boots. Your local `backend/src` and `frontend/src` are mounted
into the containers so edits hot-reload.

**Mental model of a request:** the browser talks to FastAPI over plain JSON for
most things, but chat answers come back as a *stream* (Server-Sent Events) so you
see the reply typing out live. The backend leans on three service modules for the
smart stuff — retrieval, grounding, and the LLM call — and persists everything in
Postgres via SQLAlchemy.

---

## 3. The technologies, and why each one is here

| Layer | Tech | Why it's a sensible choice |
| --- | --- | --- |
| UI | **React + Vite** | Vite gives instant hot-reload; React is the lingua franca for this kind of interactive UI. |
| Styling | **Tailwind + shadcn/Radix** | Tailwind = fast, consistent styling without leaving the markup; Radix gives accessible primitives (tooltips, dialogs) so we don't reinvent a11y. |
| Markdown | **Streamdown** | Renders the AI's markdown *as it streams*, so partial responses look right mid-type. |
| PDF | **react-pdf (pdf.js)** | Renders the actual PDF in-browser so citations can jump to a real page. |
| API | **FastAPI** | Async, typed, tiny. Its `StreamingResponse` is how we stream tokens. |
| ORM | **SQLAlchemy 2.0 (async)** | Typed models, async sessions that fit FastAPI's event loop. |
| Migrations | **Alembic** | Versioned schema changes — never hand-edit a live DB. |
| LLM glue | **PydanticAI** | A thin, typed wrapper over Claude; `run_stream` gives us token streaming for free. |
| Model | **Claude Haiku 4.5** | Fast + cheap, which matters when every keystroke-worth of answer streams. |
| PDF text | **PyMuPDF (fitz)** | Robust, fast text extraction with page boundaries. |
| DB | **PostgreSQL** | Boring, reliable, and it has the extensions (JSON, later pgvector) we'll want. |

The theme here: **boring, well-understood tools**. Good engineers don't reach for
novelty; they reach for the thing that will still make sense to the next person
at 2am. The one place we let ourselves be interesting is the retrieval/grounding
logic, because that's where the actual product value lives.

---

## 4. What we changed, and why — the decisions log

This is the part you asked for: a running record of *what* we did and *why*, so
you can reconstruct our reasoning later.

### Decision 0 — Set up the repo as a fresh repo (not a fork)
The task explicitly says "create a new repo, do not fork." So we imported the
baseline's files into your own repo with its own git history. First commit is the
untouched baseline, so every later diff is honestly *ours*.

### Decision 1 — Let the data pick the feature, not our gut
Before writing a line, we parsed `data/usage_events.csv` (50 users, 302 Q&As) and
read `data/customer_feedback.md`. The numbers and the quotes agreed loudly:
- **16%** of answers cited *zero* sources; conversations that got a 👎 had **~2×**
  the zero-source rate of 👍 ones. Un-grounded answers and distrust move together.
- **76%** of uploads were *re-uploads* of a document already used elsewhere — the
  business case for multi-document conversations.

So Part 2.1 (multi-doc) was validated by the re-upload data, and Part 2.2 became
**trust: grounded citations + a confidence signal**. (Full write-up in
`DECISIONS.md`.) Lesson: *let evidence choose the work.* It's more convincing and
you build the right thing.

### Decision 2 — Multi-document was mostly an "unlock", not a rebuild
When we read the code, we found the database schema *already* modelled documents
as a one-to-many list per conversation (`Conversation.documents`). The single-doc
limit was enforced only in three soft places: the upload service rejected a 2nd
doc, the API returned just `documents[0]`, and the UI disabled the paperclip once
a doc existed. So multi-doc meant *removing* artificial limits and *exposing* the
list, not migrating data. Lesson: **read before you rebuild** — the cheapest
feature is the one the data model already supports.

What we actually changed for multi-doc:
- Backend: removed the "one document" rejection; added `GET .../documents` to
  list them; `ConversationDetail` now returns `documents: []`; the chat endpoint
  loads *all* documents and retrieves across them.
- Frontend: a `useDocuments` hook (replacing `useDocument`); a document switcher
  in the reader; a "documents in this chat" strip; the upload button now adds
  more docs instead of locking.

### Decision 3 — Grounded citations via RAG, but *lexical* retrieval (BM25)
The baseline stuffed the *entire* document into the prompt and *asked* it to
cite. That doesn't scale to many docs, and "please cite" is not enforcement.
We rebuilt the answer path as **Retrieval-Augmented Generation**:
1. **Chunk** each document into page-aware passages (keeping page + clause
   metadata so a citation has an address).
2. **Retrieve** the top passages for the question across *all* docs.
3. **Generate** an answer constrained to only those passages, citing `[Sn]`.
4. **Verify** every `[Sn]` against the passages we actually provided — drop
   fabricated ones.
5. **Score confidence** from how much survived verification + retrieval strength.

The spicy call: retrieval is **BM25 (lexical), not vector embeddings**. Why?
Legal questions are token-heavy ("clause 12.3", "Schedule 4"), BM25 nails exact
tokens, and it needs *no* embedding API key, no vector DB, no PyTorch — it runs
in-process and deterministically, which also means the whole trust path is unit
tested with zero API calls. The honest cost: BM25 misses pure-synonym questions,
so **hybrid (BM25 + embeddings) retrieval** is the #1 upgrade (see §7).
Lesson: **match the tool to the shape of the data and the stage of the product.**
The heaviest tool is rarely the right first one.

### Decision 4 — Verification is deterministic code, not another prompt
The trust feature only means something because a *plain function* checks the
model's citations. If the model writes `[S9]` when only S1–S6 exist, we catch it,
strip it, and dock confidence. The model is never trusted to grade its own
homework. Lesson: **when correctness matters, put a deterministic check between
the model and the user.**

### Decision 5 — Upload limits (Harsh's idea 💡)
You flagged that unbounded uploads invite abuse (huge files, hundreds of docs).
Turned out file *type* (PDF-only) and *size* (25 MB) were already enforced; the
gap was *count*. We added a configurable **max 10 documents per conversation**,
enforced server-side (source of truth) and mirrored in the UI (the upload button
disables at the cap and explains why). Lesson: **defensive limits belong on the
server; the client copy is just courtesy.** Never trust the browser to enforce a
rule that protects your backend.

### Decision 6 — Stream the text, attach trust signals at the end
Answers still stream token-by-token (great UX). Citations and confidence can only
be computed once the full answer exists, so they arrive in the final SSE
`message` event and get persisted on the message (new `confidence` + `citations`
columns, migration `002`). The UI shows the streaming text live, then swaps in
the verified, citation-linked version.

### Decision 7 — Round out the multi-doc UX (upload many, remove one)
Two gaps surfaced during smoke testing: you could only pick one file at a time,
and there was no way to remove a document. Both got fixed:
- **Multi-upload**: the file inputs are `multiple`, drag-drop accepts several
  PDFs, and the hook uploads them **sequentially** (not in parallel) so the
  server-side document cap is checked race-free and the first failure — e.g.
  hitting the 10-doc limit mid-batch — surfaces cleanly.
- **Remove**: a new `DELETE /api/documents/{id}` endpoint deletes the row *and*
  the file on disk (best-effort — a missing file doesn't block the delete). In
  the UI you can remove a document from the chat's document strip (× per chip) or
  the reader's header (🗑), each behind a confirm. One sharp edge to remember: a
  message's stored citations reference a `document_id`, so citations on *old*
  answers that point at a since-deleted document will 404 if clicked — acceptable
  for now (it's history), but at scale you'd soft-delete or tombstone instead of
  hard-deleting, so the audit trail stays intact.

---

## 5. How a single question actually flows (the end-to-end trace)

Worth walking once, because it ties every module together:

1. **You type a question** → `useMessages.send()` optimistically shows your
   message and opens a streaming POST to `/api/conversations/{id}/messages`.
2. **Backend saves your message**, loads *all* documents in the conversation and
   the prior chat history.
3. **Retrieval** (`retrieve()`): every doc is chunked, BM25 ranks the chunks
   against your question, top-6 are chosen across all docs.
4. **Grounding** (`build_sources_block()`): those chunks become a numbered
   `SOURCES:` block; a map remembers which `Sn` is which chunk.
5. **LLM** (`chat_with_documents()`): PydanticAI streams Claude's answer, which
   is instructed to answer only from the sources and cite `[Sn]`. Tokens stream
   to your browser as they arrive.
6. **Verification** (`resolve_citations()`): once streaming ends, each `[Sn]` is
   checked against the source map. Valid → resolved to `{document, page,
   clause, snippet}`. Fabricated → stripped and logged.
7. **Confidence** (`compute_confidence()`): grounded / partial / unverified.
8. **Persist + final event**: the cleaned answer, citations, and confidence are
   saved and sent as the final SSE `message`. The UI renders the confidence
   badge, makes each `[Sn]` a clickable chip, and lists the sources. Click one →
   the reader panel jumps to that document and page.

---

## 6. Bugs, pitfalls, and the "how good engineers think" bits

Things we hit or deliberately avoided — these are the transferable lessons.

- **Async lazy-loading trap.** In SQLAlchemy async, touching a relationship that
  wasn't eagerly loaded throws (it can't secretly run a query mid-await). A
  freshly created conversation has no loaded `documents`, so we build its detail
  response *directly* with an empty list instead of reading `conversation.documents`.
  Pitfall to remember: **in async ORMs, "lazy" means "explode", not "fetch."**

- **Don't measure the wrong thing.** The baseline's `count_sources_cited()` used a
  regex to count the *words* "clause N" in the reply. It measured whether the
  model *said something that looks like a citation*, not whether it's *true* — the
  exact bug that lets "cited a clause that doesn't exist" happen. We replaced it
  with real verification. Lesson: **a metric that's easy to game will be gamed —
  by your own model.**

- **Streaming vs. structured output.** You can't stream a nice structured
  `{answer, citations}` object token-by-token. We resolved the tension by
  streaming plain text with inline `[Sn]` markers and computing the structured
  trust data at the end. Lesson: **pick the data shape that fits the transport;**
  don't fight the medium.

- **Server is the source of truth.** The document cap is enforced in the service
  layer. The frontend constant (`MAX_DOCUMENTS`) only shapes the UI. If we'd
  "enforced" it only in React, a curl command would blow right past it.

- **Read the schema before migrating.** We almost assumed multi-doc needed a data
  migration; it didn't. Five minutes of reading saved an hour of work.

- **Keep the trust path testable.** Choosing BM25 over an embedding API wasn't
  only about legal tokens — it kept retrieval + grounding *deterministic*, so
  `test_retrieval.py` and `test_grounding.py` cover the whole thing with no
  network and no API key. Testability is a *design input*, not an afterthought.

---

## 7. Scaling it up — from a 50-user beta to a real product

You said you want to understand everything and then decide how to grow this for a
much larger scale and user base. Here's the honest roadmap, roughly in priority
order. Today's choices are *right for a beta* and *wrong for scale* in specific,
predictable ways — that's the point of naming them.

### 7.1 Retrieval quality — go hybrid (highest leverage)
Today retrieval re-chunks every document on every question and ranks with BM25.
- **Problem at scale:** re-chunking dozens of 100-page documents per question
  gets slow, and BM25 alone misses synonym questions.
- **Upgrade:** chunk + embed **once at upload**, store chunks and vectors in
  **pgvector** (Postgres extension — no new database). At query time run **both**
  a BM25 pass and a vector pass and **fuse** them (Reciprocal Rank Fusion). You
  get exact-token precision *and* synonym recall, and retrieval becomes an
  indexed lookup instead of a full re-scan. Add a small **re-ranker** (a
  cross-encoder) on the top ~30 candidates for a final quality bump.

### 7.2 Persist chunks + embeddings (the enabling schema change)
Introduce a `document_chunks` table (`document_id`, `page`, `char offsets`,
`text`, `embedding vector`). Populate it in a **background job** on upload, not in
the request path, so a 200-page title report doesn't block the UI. This is the
foundation 7.1 sits on.

### 7.3 Ingestion as async jobs + a real file store
- **Now:** upload extracts text synchronously in the request and saves the PDF to
  local disk. Fine for one box; fatal for many.
- **Scale:** push extraction/chunking/embedding onto a **task queue** (Celery/RQ
  or a serverless worker) with a `processing → ready` status the UI polls. Store
  PDFs in **object storage (S3/GCS)**, not container disk, so any instance can
  serve any file and nothing is lost when a container recycles.

### 7.4 Multi-tenancy, auth, and isolation
There is no notion of *users* yet — every conversation is global. Before real
customers: add **authentication**, scope every row to an **organisation/user**,
and enforce it in queries (a law firm must *never* see another firm's documents).
This is table-stakes for legal software and it's a security boundary, so it wants
tests of its own.

### 7.5 Cost, latency, and abuse controls
- **Model tiering:** Haiku for routine Q&A, escalate to a larger model only for
  hard/low-confidence answers.
- **Caching:** cache embeddings and identical-question results; Anthropic prompt
  caching for the stable system prompt.
- **Rate limiting & quotas** per org; **virus/malware scanning** on uploads;
  stricter per-file and per-org storage caps than our beta's 25 MB / 10 docs.

### 7.6 Trust, evaluated — not just asserted
The confidence badge is a sound heuristic, but at scale you want to *prove* it.
- Build an **eval set** of question → expected-source pairs and measure retrieval
  recall and citation precision on every deploy (catch regressions).
- **Span-level verification:** upgrade from "the marker points at a real source"
  to "the model's quoted words actually appear in that source," and highlight the
  exact span in the PDF (PyMuPDF gives you the coordinates).
- **Close the loop:** you already log 👍/👎 — feed it back to *calibrate* the
  confidence thresholds against real outcomes instead of hand-tuned constants.

### 7.7 Observability and the boring reliability stuff
Structured logging exists (`structlog`); add **tracing** (per-request timing
across retrieve → generate → verify), **metrics** (latency, token spend,
confidence distribution, citation-fabrication rate), and **alerts**. Put the DB
behind connection pooling, add read replicas when reads dominate, and paginate
the conversation/message lists (they load everything today).

### 7.8 Product features the data is already asking for
From `customer_feedback.md`, the next most-wanted, in rough order: **document
library** (reuse a doc across conversations without re-uploading — the 76% stat),
**cross-document comparison** ("what do both docs say about indemnity?"),
**report export** (now safe to build *because* answers are grounded), and
**in-viewer search/highlight**.

**The one-line scaling summary:** move the heavy work (chunk/embed) *out of the
request and to upload-time*, make retrieval a *hybrid indexed lookup*, put real
*tenancy and auth* around it, and *measure* the trust you currently assert.

---

## 8. Where to read the code (a map for your first dive)

- Trust logic: `backend/src/takehome/services/retrieval.py` (chunk + BM25) and
  `grounding.py` (sources, citation verification, confidence). Start here.
- The orchestra: `backend/src/takehome/web/routers/messages.py` — the end-to-end
  flow from §5 lives in `send_message`.
- Multi-doc API: `routers/documents.py`, `routers/conversations.py`,
  `services/document.py`.
- Frontend trust UI: `frontend/src/components/MessageBubble.tsx` (badges +
  citation chips) and `DocumentViewer.tsx` (jump-to-page).
- Frontend state: `frontend/src/hooks/use-documents.ts`.
- Tests: `backend/tests/test_retrieval.py`, `test_grounding.py` — the clearest
  spec of how the core is supposed to behave.

Have a great session at the shop. When you're back, §7 is the conversation I'd
love to have with you. — 🤖
