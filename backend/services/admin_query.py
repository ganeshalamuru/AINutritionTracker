"""Guarded read-only SQL execution for the dev-only admin query console (routers/admin.py).

The danger lives here, isolated and unit-testable. Two independent guarantees keep it safe:

  1. **Read-only connection** (the hard guarantee): every query runs on a SQLite connection
     opened with `?mode=ro`, so the driver itself rejects any write ("attempt to write a
     readonly database") even if validation were bypassed.
  2. **Statement validation** (defense-in-depth + clean 400s): only a single SELECT/WITH
     statement is allowed; DML/DDL, PRAGMA, and ATTACH/DETACH are rejected before execution.

Secrets never leave: redact_rows() masks any cell equal to a known secret value (the configured
API keys) and blanks any credential column (`password_hash`, or a legacy `pin`), so even
`SELECT * FROM app_config` / `SELECT password_hash FROM profiles` come back scrubbed.
"""

import re
import sqlite3

from fastapi import HTTPException

REDACTED = "***REDACTED***"

# Hard row cap so a `SELECT * FROM food_nutrient` can't stream 300k rows into a response.
MAX_ROWS = 1000

# Keywords that must never appear — writes, schema changes, and ATTACH/PRAGMA (which can reach
# other files / mutate settings). Matched as whole words, case-insensitively.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex)\b",
    re.IGNORECASE,
)
_STARTS_OK = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def validate_select(sql: str) -> str:
    """Return the cleaned single-statement query, or raise HTTPException(400) if it isn't a
    lone read-only SELECT/WITH. (The read-only connection is the real guard; this is for clear
    errors and to block ATTACH/PRAGMA file access.)"""
    cleaned = (sql or "").strip().rstrip(";").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Empty query.")
    if ";" in cleaned:
        raise HTTPException(status_code=400, detail="Only a single statement is allowed.")
    if not _STARTS_OK.match(cleaned):
        raise HTTPException(status_code=400, detail="Only SELECT / WITH queries are allowed.")
    if _FORBIDDEN.search(cleaned):
        raise HTTPException(status_code=400, detail="Only read-only SELECT queries are allowed.")
    return cleaned


def run_query(db_path: str, sql: str, max_rows: int = MAX_ROWS):
    """Execute a validated SELECT on a read-only connection to `db_path`.
    Returns (columns, rows, truncated). `rows` is a list of lists, capped at `max_rows`.

    The connection is opened per call, not pooled: a SQLite connect is ~microseconds (a file
    open, no network handshake to amortize), and a fresh connection keeps each request's read
    isolated and thread-safe under FastAPI's sync-endpoint threadpool."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        try:
            cur = conn.execute(sql)
        except sqlite3.Error as e:
            # Surface the SQLite error (bad column, syntax, readonly violation) as a 400.
            raise HTTPException(status_code=400, detail=f"SQL error: {e}") from e
        columns = [d[0] for d in cur.description] if cur.description else []
        fetched = cur.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        rows = [list(r) for r in fetched[:max_rows]]
        return columns, rows, truncated
    finally:
        conn.close()


# Credential columns blanked wholesale in any result (the password hash, and a legacy PIN
# column on DBs migrated from the old profile model).
_CREDENTIAL_COLUMNS = {"password_hash", "pin"}


def redact_rows(columns: list[str], rows: list[list], secret_values: set[str]) -> list[list]:
    """Mask secrets in a result: any cell whose string equals a configured secret value becomes
    REDACTED, and every cell of a credential column (password_hash / legacy pin) is blanked.
    Mutates and returns `rows`."""
    secret_values = {s for s in secret_values if s}
    cred_idxs = {i for i, c in enumerate(columns) if (c or "").lower() in _CREDENTIAL_COLUMNS}
    for row in rows:
        for i, cell in enumerate(row):
            if i in cred_idxs:
                row[i] = REDACTED
            elif isinstance(cell, str) and cell in secret_values:
                row[i] = REDACTED
    return rows
