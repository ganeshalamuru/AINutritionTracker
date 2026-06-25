"""Unit tests for core.config.migrate_deprecated_vision_model.

Covers the startup rewrite that moves an existing install off a vision model the provider
has retired (e.g. Groq's Llama 4 Scout, decommissioned 2026-07-17) to DEFAULT_MODEL.
seed_defaults only fills *missing* keys, so without this a stored deprecated value would
persist and break analysis once the provider stops serving it.

No network, no live DB: an in-memory SQLite engine holds just the app_config table.

Run from backend/:  python -m unittest tests.test_config_migration
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401 — registers all tables on Base.metadata
from core import config
from core.database import Base

DEPRECATED = next(iter(config.DEPRECATED_VISION_MODELS))


class MigrateDeprecatedVisionModelTest(unittest.TestCase):
    def setUp(self):
        # StaticPool keeps the one in-memory connection alive across sessions.
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    def _set(self, model: str):
        db = self.Session()
        config.set_value(db, "vision_model", model)
        db.commit()
        db.close()

    def _get(self) -> str:
        db = self.Session()
        try:
            return config.get_value(db, "vision_model")
        finally:
            db.close()

    def test_rewrites_deprecated_model_to_default(self):
        self._set(DEPRECATED)
        db = self.Session()
        changed = config.migrate_deprecated_vision_model(db)
        db.close()
        self.assertTrue(changed)
        self.assertEqual(self._get(), config.DEFAULT_MODEL)

    def test_idempotent_after_migration(self):
        self._set(DEPRECATED)
        db = self.Session()
        config.migrate_deprecated_vision_model(db)
        # A second run finds the (now-current) default and does nothing.
        changed_again = config.migrate_deprecated_vision_model(db)
        db.close()
        self.assertFalse(changed_again)
        self.assertEqual(self._get(), config.DEFAULT_MODEL)

    def test_leaves_a_non_deprecated_model_untouched(self):
        self._set("gemini-2.5-flash")
        db = self.Session()
        changed = config.migrate_deprecated_vision_model(db)
        db.close()
        self.assertFalse(changed)
        self.assertEqual(self._get(), "gemini-2.5-flash")

    def test_noop_when_no_model_configured(self):
        # Fresh DB: no vision_model row -> get_value returns "" (not deprecated).
        db = self.Session()
        changed = config.migrate_deprecated_vision_model(db)
        db.close()
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
