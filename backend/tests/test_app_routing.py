"""Tests for the catch-all SPA route in main.py (serve_react).

Unknown /api paths must return a JSON 404 rather than falling through to the SPA shell
(which would hand an API client a 200 HTML page). Non-API paths still serve the frontend.

Uses TestClient WITHOUT its context manager so the app's lifespan (table creation, config
seeding, USDA/vision client builds, upload reaping) never runs — unknown-route dispatch
reaches serve_react without any DB dependency, so no startup is needed and the live DB is
left untouched.
"""

import unittest

from fastapi.testclient import TestClient

from main import app


class AppRoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_unknown_api_path_returns_json_404(self):
        resp = self.client.get("/api/does-not-exist")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"detail": "Not found"})
        self.assertIn("application/json", resp.headers.get("content-type", ""))

    def test_unknown_api_subpath_returns_json_404(self):
        resp = self.client.get("/api/meals/999/bogus")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"detail": "Not found"})

    def test_non_api_path_falls_through_to_spa(self):
        # Whether or not the frontend is built, a non-API path must NOT be the API 404:
        # it returns the index (200 HTML) or the "frontend not built yet" JSON (also 200).
        resp = self.client.get("/some/spa/route")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
