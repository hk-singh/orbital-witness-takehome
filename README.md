# Orbital — Product Engineering Take-Home

A document Q&A tool for commercial real estate lawyers: upload legal documents
(leases, title reports, environmental assessments), ask questions, and get
answers **grounded in the document content — with verifiable citations**.

This repository extends the provided baseline. Below is a summary of what was
built; the full product rationale is in **[`DECISIONS.md`](./DECISIONS.md)** and a
plain-language engineering deep-dive is in **[`FORHARSH.md`](./FORHARSH.md)**.

## 🎥 Loom walkthrough

> _Loom link: **TODO — paste 2–3 min walkthrough here before submitting**_

## What's new in this submission

**Part 2.1 — Multi-document conversations.** A conversation can now hold many
documents (not just one). You can upload **several PDFs at once** (multi-select
or drag-drop), see every document loaded in the conversation, switch between them
in the reader panel, **remove** any of them, and ask questions that draw on any
or all of them at once. A configurable cap (default **10 documents/conversation**,
PDF-only, 25 MB each) keeps things bounded.

**Part 2.2 — Grounded citations + a confidence signal.** This targets the
loudest, highest-value theme in the beta data (16% of answers cited nothing, and
👎 conversations had ~2× the zero-source rate of 👍 ones). Answers are now
produced with a small RAG pipeline:

- Documents are chunked (page- and clause-aware) and the most relevant passages
  across **all** documents are retrieved with **BM25** for each question.
- The model may answer **only** from those passages and must cite them inline
  with `[Sn]` markers.
- Every citation is **verified** against the passages actually provided —
  fabricated citations are stripped, not shown.
- Each answer carries a **confidence badge** (grounded / partially supported /
  unverified) and **clickable citations** that jump the reader to the exact
  document and page.

See `DECISIONS.md` for the data analysis and the "how it works under the hood"
walkthrough, and `FORHARSH.md` for the architecture, decisions log, and a
scaling roadmap.

## Tests & checks

```
just check                 # ruff + pyright (backend) and biome + tsc (frontend)
pytest backend/tests       # unit tests for chunking, BM25, citation verification, confidence
```

---

## Setup

### Prerequisites
- Docker and Docker Compose
- just (command runner) — install via `brew install just` or `cargo install just`

That's it. Everything else runs inside containers.

### Getting Started

1. Clone this repository

2. Run the setup command:
```
just setup
```
   This copies `.env.example` to `.env` and builds the Docker images.

3. Add your Anthropic API key to `.env`:
```
ANTHROPIC_API_KEY=your_key_here
```
   We've provided an API key in the task email. You can also use your own.

4. Start everything:
```
just dev
```
   This starts PostgreSQL, the FastAPI backend (port 8000), and the React frontend (port 5173).
   Database migrations run automatically when the backend starts — no separate step needed.

5. Open http://localhost:5173 in your browser.

Your local `backend/src/` and `frontend/src/` directories are mounted into the containers —
edit files normally on your machine and changes hot-reload automatically.

### Sample Documents

We've included sample legal documents in `sample-docs/` for testing.

### Project Structure

- `frontend/` — React frontend (Vite + Tailwind + shadcn/Radix UI)
- `backend/` — FastAPI backend (Python 3.12 + SQLAlchemy + PydanticAI)
- `alembic/` — Database migrations
- `data/` — Product analytics and customer feedback (for Part 2)
- `sample-docs/` — Sample PDF documents for testing

### Useful Commands

- `just dev` — Start full stack (Postgres + backend + frontend)
- `just stop` — Stop all services
- `just reset` — Stop everything and clear database
- `just check` — Run all linters and type checks
- `just fmt` — Format all code
- `just db-init` — Run database migrations
- `just db-shell` — Open a psql shell
- `just shell-backend` — Shell into backend container
- `just logs-backend` — Tail backend logs
