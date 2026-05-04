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

---

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
