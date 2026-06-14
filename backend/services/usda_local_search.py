"""Offline USDA search backend (the local alternative to the api.nal.usda.gov call).

When the app's `nutrition_source` is "offline", usda_service._search_usda routes here instead
of hitting the network. We query the prebuilt SQLite FTS5 index (backend/usda_local.db, created
by build_usda_db.py) and return candidate food records in the **exact shape** USDA's
/foods/search returns — so every downstream consumer in usda_service (the alias/simplify
rewriting, the _pick_best noun-gate + ranking, _extract_per_100g, the cache) is reused unchanged.

The DB is opened read-only with a short-lived connection per call: a meal fires several lookups
in parallel on usda_service's worker pool, and a fresh read-only connection per query is both
trivially cheap (a ~10 MB file) and free of cross-thread cursor hazards.
"""

import logging
import os
import re
import sqlite3

from core.config import BACKEND_DIR

logger = logging.getLogger("nutriai.nutrition_db")

DB_PATH = os.path.join(BACKEND_DIR, "usda_local.db")

# Fetch more candidates than the online USDA_PAGE_SIZE (5): local search has no network cost,
# and _pick_best re-ranks the candidates with its own gate, so a wider net only helps matching.
LOCAL_CANDIDATE_LIMIT = 25

# Tokenize a query into alphanumeric terms (matches the FTS unicode61 tokenizer's word split),
# so we can quote each term and avoid feeding FTS5 operators/punctuation from a food name.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Logged at most once when the DB is missing, so a misconfigured offline mode is obvious but
# doesn't spam a line per ingredient lookup.
_warned_missing = False


def is_available() -> bool:
    """True if the offline search DB exists (built by build_usda_db.py)."""
    return os.path.exists(DB_PATH)


def _match_expr(query: str, require_all: bool) -> str:
    """Build an FTS5 MATCH string from a query: each term quoted (literal), joined by AND for a
    strict search or OR for the loose retry. Returns '' when the query has no usable terms."""
    tokens = _TOKEN_RE.findall((query or "").lower())
    if not tokens:
        return ""
    quoted = [f'"{t}"' for t in tokens]
    return (" AND " if require_all else " OR ").join(quoted)


def _nutrients_for(conn: sqlite3.Connection, fdc_id: int) -> list[dict]:
    """The stored per-100g nutrient rows for a food, shaped like USDA's foodNutrients."""
    rows = conn.execute(
        "SELECT nutrient_id, amount FROM food_nutrients WHERE fdc_id = ?", (fdc_id,)
    ).fetchall()
    return [{"nutrientId": nid, "value": amt} for nid, amt in rows]


def search(
    query: str,
    require_all: bool = True,
    data_types: list | None = None,
    page_size: int = LOCAL_CANDIDATE_LIMIT,
) -> list:
    """Local stand-in for usda_service._search_usda: return USDA-shaped candidate dicts
    ({description, dataType, fdcId, score, foodNutrients}) for `query`, ranked by BM25.

    `data_types` filters on the API display strings stored in the DB ('Foundation',
    'SR Legacy', 'Survey (FNDDS)') — same values usda_service passes for ingredient vs dish
    searches. Returns [] when the query is empty, the DB is missing, or nothing matches
    (treated as a definitive miss upstream, identical to a 0-hit USDA response)."""
    global _warned_missing
    if not is_available():
        if not _warned_missing:
            logger.warning(
                "offline USDA db missing at %s — run `python build_usda_db.py`. "
                "Switch Settings -> nutrition source to online, or build the db.",
                DB_PATH,
            )
            _warned_missing = True
        return []

    match = _match_expr(query, require_all)
    if not match:
        return []

    sql = (
        "SELECT f.fdc_id, f.description, f.data_type, bm25(foods_fts) AS rank "
        "FROM foods_fts JOIN foods f ON f.fdc_id = foods_fts.rowid "
        "WHERE foods_fts MATCH ?"
    )
    params: list = [match]
    if data_types:
        placeholders = ", ".join("?" for _ in data_types)
        sql += f" AND f.data_type IN ({placeholders})"
        params.extend(data_types)
    sql += " ORDER BY rank LIMIT ?"
    params.append(page_size)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        try:
            hits = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            # A malformed FTS expression should fail soft (miss), never crash the meal.
            logger.warning("offline search failed for %r: %s", query, e)
            return []
        foods = []
        for fdc_id, description, data_type, rank in hits:
            foods.append(
                {
                    "description": description,
                    "dataType": data_type,
                    "fdcId": fdc_id,
                    # bm25 is more-negative-is-better; negate so higher score = better match,
                    # matching _pick_best's `-(score)` final tiebreak.
                    "score": -rank,
                    "foodNutrients": _nutrients_for(conn, fdc_id),
                }
            )
    finally:
        conn.close()

    logger.info(
        "local search %r (%s) | %d hits", query, "strict" if require_all else "loose", len(foods)
    )
    return foods


def get_food(fdc_id: int) -> dict | None:
    """One food by id as a USDA-shaped dict ({description, dataType, fdcId, foodNutrients}),
    or None if the id isn't in the index / the DB is missing. Mirrors search()'s shape so the
    foods API can reuse usda_service._extract_per_100g."""
    if not is_available():
        return None
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT fdc_id, description, data_type FROM foods WHERE fdc_id = ?", (fdc_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "fdcId": row[0],
            "description": row[1],
            "dataType": row[2],
            "foodNutrients": _nutrients_for(conn, row[0]),
        }
    finally:
        conn.close()


def table_counts() -> dict[str, int]:
    """Table name -> row count for the offline index (for the admin tables view). Empty if
    the DB is missing. Skips internal FTS shadow tables."""
    if not is_available():
        return {}
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'foods_fts_%' "
                "ORDER BY name"
            ).fetchall()
        ]
        counts = {}
        for name in names:
            counts[name] = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        return counts
    finally:
        conn.close()
