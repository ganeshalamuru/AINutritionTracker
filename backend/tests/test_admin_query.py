"""Tests for the guarded read-only SQL service (services/admin_query.py).

No HTTP: validates the SQL guard, the read-only execution (incl. that a write is blocked at the
driver level even if validation were bypassed), row capping, and secret/PIN redaction. Each test
uses a throwaway SQLite file.
"""

import os
import sqlite3
import tempfile
import unittest

from fastapi import HTTPException

import services.admin_query as aq


class ValidateSelectTest(unittest.TestCase):
    def test_accepts_select_and_with(self):
        self.assertEqual(aq.validate_select("SELECT 1"), "SELECT 1")
        self.assertEqual(aq.validate_select("  select * from foods ;  "), "select * from foods")
        self.assertTrue(
            aq.validate_select("WITH x AS (SELECT 1) SELECT * FROM x").startswith("WITH")
        )

    def test_rejects_writes_and_ddl(self):
        for bad in (
            "DELETE FROM foods",
            "UPDATE foods SET x=1",
            "INSERT INTO foods VALUES (1)",
            "DROP TABLE foods",
            "create table t (a)",
            "REPLACE INTO foods VALUES (1)",
        ):
            with self.assertRaises(HTTPException):
                aq.validate_select(bad)

    def test_rejects_pragma_attach_and_multistatement(self):
        for bad in (
            "PRAGMA table_info(foods)",
            "ATTACH DATABASE 'other.db' AS o",
            "SELECT 1; DROP TABLE foods",
            "",
            "   ",
        ):
            with self.assertRaises(HTTPException):
                aq.validate_select(bad)


class RunQueryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        conn = sqlite3.connect(self._tmp.name)
        conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        conn.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"row{i}") for i in range(10)])
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self._tmp.name)

    def test_returns_columns_and_rows(self):
        cols, rows, truncated = aq.run_query(
            self._tmp.name, "SELECT id, name FROM t ORDER BY id LIMIT 3"
        )
        self.assertEqual(cols, ["id", "name"])
        self.assertEqual(rows, [[0, "row0"], [1, "row1"], [2, "row2"]])
        self.assertFalse(truncated)

    def test_row_cap_sets_truncated(self):
        cols, rows, truncated = aq.run_query(self._tmp.name, "SELECT * FROM t", max_rows=4)
        self.assertEqual(len(rows), 4)
        self.assertTrue(truncated)

    def test_readonly_connection_blocks_writes(self):
        # Even bypassing validate_select, the mode=ro connection must reject a write -> 400.
        with self.assertRaises(HTTPException) as ctx:
            aq.run_query(self._tmp.name, "UPDATE t SET name='x'")
        self.assertEqual(ctx.exception.status_code, 400)
        # And the data is unchanged.
        conn = sqlite3.connect(self._tmp.name)
        self.assertEqual(conn.execute("SELECT name FROM t WHERE id=0").fetchone()[0], "row0")
        conn.close()

    def test_bad_sql_is_400(self):
        with self.assertRaises(HTTPException) as ctx:
            aq.run_query(self._tmp.name, "SELECT nope FROM t")
        self.assertEqual(ctx.exception.status_code, 400)


class RedactRowsTest(unittest.TestCase):
    def test_masks_secret_values(self):
        cols = ["key", "value"]
        rows = [["groq_api_key", "gsk_secret"], ["nutrition_source", "offline"]]
        out = aq.redact_rows(cols, rows, {"gsk_secret", ""})
        self.assertEqual(out, [["groq_api_key", aq.REDACTED], ["nutrition_source", "offline"]])

    def test_masks_credential_columns_regardless_of_value(self):
        # Both the password hash and a legacy pin column are blanked wholesale.
        cols = ["id", "password_hash", "pin", "name"]
        rows = [[1, "$2b$abc", "1234", "Ann"], [2, "$2b$def", "0000", "Bob"]]
        out = aq.redact_rows(cols, rows, set())
        self.assertEqual([r[1] for r in out], [aq.REDACTED, aq.REDACTED])  # password_hash
        self.assertEqual([r[2] for r in out], [aq.REDACTED, aq.REDACTED])  # pin
        self.assertEqual([r[3] for r in out], ["Ann", "Bob"])  # other columns untouched

    def test_empty_secret_set_is_noop_on_values(self):
        cols = ["value"]
        rows = [["anything"]]
        self.assertEqual(aq.redact_rows(cols, rows, set()), [["anything"]])


class AdminSecretKeyTest(unittest.TestCase):
    """The admin data-inspection views must treat the JWT signing secret as secret (not just
    the *_api_key values) — exposing jwt_secret would let an admin forge tokens for any user."""

    def test_jwt_secret_and_api_keys_are_secret(self):
        from routers import admin

        self.assertTrue(admin._is_secret_key("jwt_secret"))
        self.assertTrue(admin._is_secret_key("groq_api_key"))
        self.assertTrue(admin._is_secret_key("gemini_api_key"))
        self.assertFalse(admin._is_secret_key("nutrition_source"))
        self.assertFalse(admin._is_secret_key("vision_provider"))


if __name__ == "__main__":
    unittest.main()
