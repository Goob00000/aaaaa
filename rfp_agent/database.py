"""
SQLite persistence layer for jobs, results, and the library entry cache.
"""

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "rfp_agent.db"


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id           TEXT PRIMARY KEY,
                filename     TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'processing',
                total        INTEGER NOT NULL DEFAULT 0,
                processed    INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS results (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id             TEXT NOT NULL,
                original_question  TEXT NOT NULL,
                detected_category  TEXT,
                matched_topic      TEXT,
                draft_answer       TEXT,
                updated_by         TEXT,
                review_status      TEXT DEFAULT 'Draft',
                match_score        REAL,
                needs_review       INTEGER DEFAULT 0,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS library_entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topic       TEXT NOT NULL,
                response    TEXT NOT NULL,
                category    TEXT,
                keywords    TEXT,
                ingested_at TEXT NOT NULL
            );
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── Jobs ──────────────────────────────────────────────────────────────────────

def create_job(filename: str, total: int) -> str:
    job_id = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO jobs (id, filename, created_at, status, total, processed) VALUES (?,?,?,'processing',?,0)",
            (job_id, filename, datetime.now().isoformat(), total),
        )
    return job_id


def update_job_progress(job_id: str, processed: int):
    with _conn() as c:
        c.execute("UPDATE jobs SET processed=? WHERE id=?", (processed, job_id))


def finish_job(job_id: str, error: str = None):
    with _conn() as c:
        if error:
            c.execute("UPDATE jobs SET status='error', error_message=? WHERE id=?", (error, job_id))
        else:
            c.execute("UPDATE jobs SET status='done' WHERE id=?", (job_id,))


def get_job(job_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()]


# ── Results ───────────────────────────────────────────────────────────────────

def insert_result(job_id: str, row: dict):
    with _conn() as c:
        c.execute(
            """INSERT INTO results
               (job_id, original_question, detected_category, matched_topic,
                draft_answer, updated_by, review_status, match_score, needs_review)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                row["original_question"],
                row["detected_category"],
                row["matched_topic"],
                row["draft_answer"],
                row["updated_by"],
                row["review_status"],
                row["match_score"],
                1 if row["needs_review"] else 0,
            ),
        )


def get_results(job_id: str, category: str = None, status: str = None) -> list[dict]:
    sql = "SELECT * FROM results WHERE job_id=?"
    params: list = [job_id]
    if category:
        sql += " AND detected_category=?"
        params.append(category)
    if status:
        sql += " AND review_status=?"
        params.append(status)
    sql += " ORDER BY id"
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def get_job_categories(job_id: str) -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT detected_category FROM results WHERE job_id=? ORDER BY detected_category",
            (job_id,),
        ).fetchall()
        return [r[0] for r in rows if r[0]]


def get_job_stats(job_id: str) -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM results WHERE job_id=?", (job_id,)).fetchone()[0]
        needs = c.execute("SELECT COUNT(*) FROM results WHERE job_id=? AND needs_review=1", (job_id,)).fetchone()[0]
        approved = c.execute("SELECT COUNT(*) FROM results WHERE job_id=? AND review_status='Approved'", (job_id,)).fetchone()[0]
        published = c.execute("SELECT COUNT(*) FROM results WHERE job_id=? AND review_status='Published'", (job_id,)).fetchone()[0]
    return {"total": total, "needs_review": needs, "approved": approved, "published": published}


def update_result(result_id: int, **fields) -> bool:
    allowed = {"draft_answer", "updated_by", "review_status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k}=?" for k in updates)
    with _conn() as c:
        c.execute(f"UPDATE results SET {set_clause} WHERE id=?", [*updates.values(), result_id])
    return True


# ── Library entries ───────────────────────────────────────────────────────────

def upsert_library_entries(entries: list[dict]):
    now = datetime.now().isoformat()
    with _conn() as c:
        c.execute("DELETE FROM library_entries")
        c.executemany(
            "INSERT INTO library_entries (topic, response, category, keywords, ingested_at) VALUES (?,?,?,?,?)",
            [(e["topic"], e["response"], e["category"], e.get("keywords", ""), now) for e in entries],
        )


def get_library_entries(category: str = None, search: str = None, limit: int = 50, offset: int = 0):
    base = "FROM library_entries WHERE 1=1"
    params: list = []
    if category:
        base += " AND category=?"
        params.append(category)
    if search:
        base += " AND (topic LIKE ? OR response LIKE ? OR keywords LIKE ?)"
        params.extend([f"%{search}%"] * 3)
    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        rows = c.execute(f"SELECT * {base} ORDER BY category, topic LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
    return [dict(r) for r in rows], total


def get_library_categories() -> list[str]:
    with _conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT category FROM library_entries ORDER BY category").fetchall() if r[0]]


def get_library_count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM library_entries").fetchone()[0]
