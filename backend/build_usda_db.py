"""Build the offline USDA search database (one-time ETL, run manually).

Reads the USDA FoodData Central bulk CSV export under `../usda_data/` and writes a
compact, searchable SQLite file `backend/usda_local.db` that the offline nutrient-lookup
backend (services/usda_local_search.py) queries with FTS5 — replacing the network call
to api.nal.usda.gov when the app's `nutrition_source` is set to "offline".

Only the three real generic/dish data types are kept (~13.7k foods); the ~87k Foundation
analytical-sample rows (sub_sample_food / market_acquisition / sample_food) are dropped.
Only the nutrients we actually track (FDC_NUTRIENT_MAP + energy fallbacks) are stored.

Run from the backend/ directory:
    python build_usda_db.py

Re-run only when the USDA dataset under usda_data/ is refreshed. The output file is
gitignored; the app opens it read-only if present (see services/usda_local_search.py).
"""

import csv
import glob
import os
import sqlite3
import sys

from core.config import BACKEND_DIR
from services.nutrition_data import ENERGY_FALLBACK_IDS, FDC_NUTRIENT_MAP

# The CSV `data_type` strings -> the API display strings the matching code expects
# (DATA_TYPE_RANK / DISH_DATA_TYPES in services/nutrition_data/config.py). Foods whose
# data_type isn't a key here are skipped (analytical samples, branded, etc.).
DATA_TYPE_DISPLAY = {
    "foundation_food": "Foundation",
    "sr_legacy_food": "SR Legacy",
    "survey_fndds_food": "Survey (FNDDS)",
}

USDA_DATA_DIR = os.path.join(BACKEND_DIR, "..", "usda_data")
OUTPUT_DB = os.path.join(BACKEND_DIR, "usda_local.db")

# Nutrient IDs worth storing: the ones we map to our schema, plus the energy fallbacks.
KEEP_NUTRIENT_IDS = set(FDC_NUTRIENT_MAP) | set(ENERGY_FALLBACK_IDS)

# csv fields can exceed the default limit on some rows; raise it generously.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _dataset_dirs() -> list[str]:
    """Every directory under usda_data/ that holds a food.csv (handles the doubly-nested
    folders the USDA zips expand into)."""
    pattern = os.path.join(USDA_DATA_DIR, "**", "food.csv")
    return sorted({os.path.dirname(p) for p in glob.glob(pattern, recursive=True)})


def _load_foods(dataset_dir: str) -> dict[int, tuple[str, str]]:
    """fdc_id -> (description, display_data_type) for the kept data types in one dataset."""
    foods: dict[int, tuple[str, str]] = {}
    with open(os.path.join(dataset_dir, "food.csv"), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            display = DATA_TYPE_DISPLAY.get(row["data_type"])
            if not display:
                continue
            try:
                fdc_id = int(row["fdc_id"])
            except (ValueError, KeyError):
                continue
            foods[fdc_id] = (row["description"], display)
    return foods


def _nutrient_translation(dataset_dir: str) -> dict[int, int]:
    """Map a dataset's `food_nutrient.nutrient_id` values to canonical FDC nutrient ids,
    for the nutrients we keep only.

    Foundation/SR Legacy reference nutrients by FDC `id` (e.g. 1008), but the FNDDS/Survey
    export references them by the legacy `nutrient_nbr` (e.g. 208) instead. Each dataset's
    own nutrient.csv carries both columns, so we accept either: identity for the FDC id,
    plus nutrient_nbr -> id.

    `nutrient_nbr` is NOT unique across all nutrients (e.g. 205 is shared by
    Carbohydrate-by-difference id 1005 and the summation variant id 1050), and losing track
    of that once silently zeroed FNDDS carbs. But restricting the map to KEEP_NUTRIENT_IDS
    drops the untracked sibling (1050) before it can collide, so within the kept subset the
    nbr is unique and no preference logic is needed. The assert guards that invariant in case
    USDA ever adds a tracked nutrient that breaks it. (Kept nbrs are <1000 and kept ids are
    >=1000, so id-space and nbr-space never overlap either.)"""
    out: dict[int, int] = {}
    with open(os.path.join(dataset_dir, "nutrient.csv"), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                nid = int(row["id"])
            except (ValueError, KeyError):
                continue
            if nid not in KEEP_NUTRIENT_IDS:
                continue
            out[nid] = nid  # Foundation/SR Legacy reference by FDC id
            try:
                nbr = int(float(row["nutrient_nbr"]))
            except (ValueError, KeyError, TypeError):
                continue
            assert nbr not in out or out[nbr] == nid, (
                f"nutrient_nbr {nbr} collides among tracked ids in {dataset_dir}"
            )
            out[nbr] = nid  # Survey/FNDDS reference by nutrient_nbr
    return out


def _load_nutrients(dataset_dir: str, keep_ids: set[int]):
    """Yield (fdc_id, nutrient_id, amount) for kept foods + tracked nutrients in one dataset.
    Nutrient references are normalized to canonical FDC ids (see _nutrient_translation)."""
    translate = _nutrient_translation(dataset_dir)
    path = os.path.join(dataset_dir, "food_nutrient.csv")
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                fdc_id = int(row["fdc_id"])
                raw_nid = int(row["nutrient_id"])
            except (ValueError, KeyError):
                continue
            if fdc_id not in keep_ids:
                continue
            nutrient_id = translate.get(raw_nid)  # None for nutrients we don't keep
            if nutrient_id is None:
                continue
            amount = row.get("amount")
            if amount in (None, ""):
                continue
            try:
                yield fdc_id, nutrient_id, float(amount)
            except ValueError:
                continue


def _create_schema(conn: sqlite3.Connection):
    conn.executescript(
        """
        DROP TABLE IF EXISTS foods_fts;
        DROP TABLE IF EXISTS foods;
        DROP TABLE IF EXISTS food_nutrients;

        CREATE TABLE foods (
            fdc_id      INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            data_type   TEXT NOT NULL
        );
        CREATE TABLE food_nutrients (
            fdc_id      INTEGER NOT NULL,
            nutrient_id INTEGER NOT NULL,
            amount      REAL NOT NULL
        );
        CREATE INDEX idx_food_nutrients_fdc ON food_nutrients (fdc_id);

        -- External-content FTS index over the description (no text duplication); rowid is fdc_id.
        CREATE VIRTUAL TABLE foods_fts USING fts5(
            description,
            content='foods',
            content_rowid='fdc_id',
            tokenize='porter unicode61'
        );
        """
    )


def build():
    dataset_dirs = _dataset_dirs()
    if not dataset_dirs:
        raise SystemExit(
            f"No food.csv found under {USDA_DATA_DIR!r}. "
            "Download the USDA FoodData Central CSV export into usda_data/ first."
        )

    print(f"Output: {OUTPUT_DB}")
    conn = sqlite3.connect(OUTPUT_DB)
    try:
        _create_schema(conn)

        all_fdc_ids: set[int] = set()
        total_foods = 0
        total_nutrients = 0

        for dataset_dir in dataset_dirs:
            label = os.path.basename(dataset_dir)
            foods = _load_foods(dataset_dir)
            if not foods:
                print(f"  {label}: no kept foods, skipping")
                continue
            conn.executemany(
                "INSERT OR REPLACE INTO foods (fdc_id, description, data_type) VALUES (?, ?, ?)",
                [(fid, desc, dt) for fid, (desc, dt) in foods.items()],
            )
            keep_ids = set(foods)
            all_fdc_ids |= keep_ids

            n_count = 0
            for batch in _batched(_load_nutrients(dataset_dir, keep_ids), 5000):
                conn.executemany(
                    "INSERT INTO food_nutrients (fdc_id, nutrient_id, amount) VALUES (?, ?, ?)",
                    batch,
                )
                n_count += len(batch)
            conn.commit()
            total_foods += len(foods)
            total_nutrients += n_count
            print(f"  {label}: {len(foods):>6} foods, {n_count:>7} nutrient rows")

        # Populate the FTS index from the content table.
        conn.execute("INSERT INTO foods_fts (foods_fts) VALUES ('rebuild')")
        conn.commit()
        conn.execute("VACUUM")

        size_mb = os.path.getsize(OUTPUT_DB) / (1024 * 1024)
        print(
            f"\nDone: {total_foods} foods, {total_nutrients} nutrient rows "
            f"({len(all_fdc_ids)} distinct fdc_ids) -> {size_mb:.1f} MB"
        )
    finally:
        conn.close()


def _batched(iterable, size):
    """Yield lists of up to `size` items from an iterable (avoids buffering 600k rows)."""
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


if __name__ == "__main__":
    build()
