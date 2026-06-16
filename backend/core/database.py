import os

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Anchor the SQLite file to backend/ rather than the process CWD, matching how core.config
# resolves BACKEND_DIR. Computed locally (not imported from core.config) to avoid an import
# cycle: config -> models -> core.database. Forward slashes keep the URI valid on Windows too.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_BACKEND_DIR, "nutrition.db").replace(os.sep, "/")
DATABASE_URL = f"sqlite:///{_DB_PATH}"

# File-based SQLite already gets SQLAlchemy's QueuePool by default, so basic connection
# pooling is in place. The production-meaningful tuning for SQLite isn't pool size but
# the per-connection PRAGMAs below (set in the `connect` listener): under this app's
# concurrent access (the USDA ThreadPoolExecutor + asyncio.to_thread workers all touch
# the DB), WAL mode + busy_timeout are what actually prevent "database is locked".
# pool_pre_ping transparently discards any connection that has gone stale.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _connection_record):
    """Apply SQLite reliability/concurrency pragmas on every new connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
    cursor.execute("PRAGMA busy_timeout=5000")  # wait up to 5s for a lock vs. erroring
    cursor.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, much faster than FULL
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Deterministic names for indexes/constraints (consistency + forward-compatible with
# migrations). Applies to freshly created constraints; harmless to the existing DB file.
_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_NAMING_CONVENTION)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
