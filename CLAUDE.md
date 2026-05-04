# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo contains two independent projects:

- **Root** — a legacy Morph.io scraper (`scraper.py`, `requirements.txt`, `runtime.txt`). Not actively developed.
- **`rfp_agent/`** — the active project: an autonomous RFP response agent with a FastAPI web UI.

All active development happens inside `rfp_agent/`. Run every command from that directory.

## Running the web app

```bash
cd rfp_agent
export ANTHROPIC_API_KEY=sk-...
uvicorn server:app --reload --port 8000
```

## CLI (headless)

```bash
cd rfp_agent
# Load the response library (once, or after updates)
python main.py ingest --library data/predefined_responses.xlsx [--reset]

# Process an RFP questions spreadsheet
python main.py respond --rfp data/new_rfp.xlsx --output data/rfp_response.xlsx [--updated_by "Jane Smith"]
```

## Architecture

### Processing pipeline

Every RFP question flows through three sequential steps, all in `agent.py`:

1. **Categorize** (`categorize_question`) — Claude Haiku classifies the question into one of 8 categories (Financial/Commercial, Technical, Business/Operations, Legal/Compliance, Security/Privacy, HR/Staffing, Project Management, Other).
2. **Match** (`match_responses`) — ChromaDB cosine similarity search against the predefined response library, filtered by category with a global fallback if the category yields no results.
3. **Draft** (`draft_answer`) — Claude Sonnet generates a grounded response using the top-k matches as context. Returns `review_status="Pending Review"` and `needs_review=True` when `match_score < 0.55`.

The entry point for a single question is `RFPAgent.process_question()`.

### Knowledge base

`ingest.py` populates a ChromaDB persistent collection (`rfp_predefined_responses`) from a `predefined_responses.xlsx` spreadsheet. Each entry is embedded as `"{topic}. Keywords: {keywords}. {response[:300]}"` using `all-MiniLM-L6-v2`. Entries with no `category` column are auto-classified by Claude Haiku on ingest. `ingest()` returns the categorized DataFrame so callers (e.g. `server.py`) can mirror entries into SQLite.

### Web app (`server.py`)

FastAPI app with Jinja2 templates (Bootstrap 5) and vanilla JS. Key design points:

- **Library ingest** runs via `asyncio.to_thread` to avoid blocking the event loop.
- **RFP processing** spawns a plain `threading.Thread` per job. Progress is written to SQLite after each question; the browser polls `/jobs/{id}/status` every 2 seconds and reloads on completion.
- **Inline edits** (`review_status`, `updated_by`, `draft_answer`) are saved via `PATCH /results/{id}` with a JSON body. Only those three fields are accepted; everything else is rejected in `update_result()`.
- **Excel download** (`/jobs/{id}/download`) regenerates the spreadsheet on the fly from SQLite — it is never stored on disk.
- `TemplateResponse` uses the **Starlette 0.31+ API**: `templates.TemplateResponse(request, "template.html", context)` — `request` is the first positional arg, not a key in the context dict. Using the old style breaks Jinja2's LRU cache.

### Persistence (`database.py`)

SQLite at `data/rfp_agent.db` with three tables:

| Table | Purpose |
|---|---|
| `jobs` | One row per processing run (status, progress counter) |
| `results` | One row per question/answer pair, editable via the UI |
| `library_entries` | Mirror of the ChromaDB library for browsable UI — replaced wholesale on each ingest |

Each function opens and closes its own connection via the `_conn()` context manager, making it safe to call from background threads.

### Spreadsheet formats

**Library input** (`predefined_responses.xlsx`): `topic` (required), `response` (required), `category` (optional, auto-assigned), `keywords` (optional).

**RFP input** (`new_rfp.xlsx`): one column named `question`.

**Output columns**: `original_question | detected_category | matched_topic | draft_answer | updated_by | review_status | match_score | needs_review`

## Environment

`ANTHROPIC_API_KEY` must be set. No other secrets are required. ChromaDB and the SQLite DB are created automatically on first run under `rfp_agent/knowledge_base/` and `rfp_agent/data/` respectively — both are gitignored.
