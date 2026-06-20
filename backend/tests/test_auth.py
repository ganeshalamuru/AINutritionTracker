"""Integration tests for authentication + authorization (routers/auth.py, routers/users.py,
and the ownership scoping added to meals/nutrition).

No network and no live DB: a throwaway temp SQLite DB is wired in by overriding the get_db
dependency, JWT_SECRET is set so token signing needs no app_config, and TestClient is used
WITHOUT its context manager so the app lifespan (which would touch the real nutrition.db and
build USDA/vision clients) never runs. Tables are created directly on the temp engine.

Run from backend/:  python -m unittest tests.test_auth
"""

import os
import tempfile
import unittest

os.environ["JWT_SECRET"] = "test-secret-do-not-use-in-prod-0123456789abcdef"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401 — registers all tables on Base.metadata
from core.database import Base, get_db
from main import app


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


_NUTRIENTS = {"calories": 100, "protein_g": 5}


class AuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        cls._engine = create_engine(
            f"sqlite:///{cls._tmp.name}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=cls._engine)
        cls._Session = sessionmaker(bind=cls._engine, autoflush=False, autocommit=False)

        def _override_get_db():
            db = cls._Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls._engine.dispose()
        os.unlink(cls._tmp.name)

    # --- helpers -------------------------------------------------------------

    def _register(self, username, password="password123", **kw):
        return self.client.post(
            "/api/auth/register", json={"username": username, "password": password, **kw}
        )

    def _login(self, username, password="password123"):
        return self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )

    def _access(self, username, password="password123"):
        """The in-memory access token from a login (the refresh token rides in a cookie now)."""
        return self._login(username, password).json()["access_token"]

    # --- registration / roles -----------------------------------------------

    def test_01_first_user_is_admin_rest_are_users(self):
        r = self._register("alice")
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["user"]["role"], "admin")
        self.assertEqual(body["user"]["username"], "alice")
        self.assertTrue(body["access_token"])
        # The refresh token must NOT be in the body — it's delivered as an HttpOnly cookie scoped
        # to /api/auth, so JS (and an XSS payload) can't read it.
        self.assertNotIn("refresh_token", body)
        set_cookie = r.headers.get("set-cookie", "")
        self.assertIn("nutriai_refresh=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("Path=/api/auth", set_cookie)

        r2 = self._register("bob")
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r2.json()["user"]["role"], "user")

    def test_02_duplicate_username_conflicts(self):
        r = self._register("ALICE")  # case-insensitive
        self.assertEqual(r.status_code, 409)

    def test_03_short_password_rejected(self):
        r = self._register("carol", password="short")
        self.assertEqual(r.status_code, 422)

    # --- login ---------------------------------------------------------------

    def test_04_login_wrong_password_401(self):
        self.assertEqual(self._login("alice", "wrongpass").status_code, 401)

    def test_05_login_unknown_user_401(self):
        self.assertEqual(self._login("nobody").status_code, 401)

    def test_06_me_requires_and_returns_user(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        token = self._access("alice")
        r = self.client.get("/api/auth/me", headers=_auth(token))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["username"], "alice")

    # --- protected endpoints + ownership scoping -----------------------------

    def test_07_meals_require_auth(self):
        self.assertEqual(self.client.get("/api/meals/timeline").status_code, 401)
        self.assertEqual(self.client.get("/api/nutrition/daily").status_code, 401)

    def test_08_meal_is_owner_scoped(self):
        alice = self._access("alice")
        bob = self._access("bob")

        logged = self.client.post(
            "/api/meals/log",
            headers=_auth(alice),
            json={"meal_name": "Alice lunch", "meal_type": "lunch", "nutrients": _NUTRIENTS},
        )
        self.assertEqual(logged.status_code, 201, logged.text)
        meal_id = logged.json()["id"]

        # Owner sees it; other user gets a 404 (not 403 — no existence leak).
        self.assertEqual(
            self.client.get(f"/api/meals/{meal_id}", headers=_auth(alice)).status_code, 200
        )
        self.assertEqual(
            self.client.get(f"/api/meals/{meal_id}", headers=_auth(bob)).status_code, 404
        )
        self.assertEqual(
            self.client.delete(f"/api/meals/{meal_id}", headers=_auth(bob)).status_code, 404
        )

        # Bob's timeline doesn't include Alice's meal.
        bob_timeline = self.client.get("/api/meals/timeline", headers=_auth(bob)).json()
        self.assertEqual(bob_timeline["total"], 0)

    # --- admin authorization -------------------------------------------------

    def test_09_admin_only_endpoints(self):
        alice = self._access("alice")  # admin
        bob = self._access("bob")  # user

        self.assertEqual(self.client.get("/api/users", headers=_auth(bob)).status_code, 403)
        self.assertEqual(self.client.get("/api/users", headers=_auth(alice)).status_code, 200)
        # Config holds API keys — admin only.
        self.assertEqual(self.client.get("/api/config", headers=_auth(bob)).status_code, 403)
        self.assertEqual(self.client.get("/api/config", headers=_auth(alice)).status_code, 200)

    # --- refresh-token rotation ----------------------------------------------

    def test_10_refresh_rotates_and_detects_reuse(self):
        # A fresh client so the cookie jar is isolated from the other tests' logins.
        c = TestClient(app)
        c.post("/api/auth/login", json={"username": "bob", "password": "password123"})
        old_refresh = c.cookies.get("nutriai_refresh")
        self.assertTrue(old_refresh)

        # Refresh sends the cookie (no body); the response carries only the access token.
        r = c.post("/api/auth/refresh")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["access_token"])
        new_refresh = c.cookies.get("nutriai_refresh")
        self.assertNotEqual(new_refresh, old_refresh)

        # Reusing the rotated (now-revoked) token fails. Replant it as the only cookie.
        c.cookies.clear()
        c.cookies.set("nutriai_refresh", old_refresh)
        self.assertEqual(c.post("/api/auth/refresh").status_code, 401)
        # Reuse triggers chain revocation, so the freshly issued one is now dead too.
        c.cookies.clear()
        c.cookies.set("nutriai_refresh", new_refresh)
        self.assertEqual(c.post("/api/auth/refresh").status_code, 401)

    # --- change password -----------------------------------------------------

    def test_11_change_password(self):
        token = self._access("bob")
        # Wrong current password -> 400.
        bad = self.client.post(
            "/api/auth/change-password",
            headers=_auth(token),
            json={"current_password": "nope", "new_password": "newpassword1"},
        )
        self.assertEqual(bad.status_code, 400)

        ok = self.client.post(
            "/api/auth/change-password",
            headers=_auth(token),
            json={"current_password": "password123", "new_password": "newpassword1"},
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self._login("bob", "password123").status_code, 401)
        self.assertEqual(self._login("bob", "newpassword1").status_code, 200)


if __name__ == "__main__":
    unittest.main()
