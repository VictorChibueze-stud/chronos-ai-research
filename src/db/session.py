from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


DATABASE_URL = "sqlite:///data/chronos.db"


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def _migrate_add_mtf_alignment() -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE monitored_setups ADD COLUMN mtf_alignment JSON"))
    except Exception:
        # Column already exists (or table not yet created in this process).
        pass


def _migrate_add_ema_signal() -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE monitored_setups ADD COLUMN ema_signal VARCHAR"))
    except Exception:
        # Column already exists (or table not yet created in this process).
        pass


def _cleanup_monitored_setups_safety_valve() -> None:
    """Bound runaway growth from old scans before API routes are used.

    If monitored_setups grows above 200 rows, trim it down to 150 by deleting
    lowest-scoring rows first (and oldest id as tie-breaker).
    """
    try:
        with engine.begin() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM monitored_setups")).scalar() or 0
            if int(total) <= 200:
                return
            conn.execute(
                text(
                    """
                    DELETE FROM monitored_setups
                    WHERE id IN (
                        SELECT id
                        FROM monitored_setups
                        ORDER BY trend_score ASC, id DESC
                        LIMIT :to_delete
                    )
                    """
                ),
                {"to_delete": int(total) - 150},
            )
    except Exception:
        # Table may not exist yet during first boot, or cleanup may race startup.
        pass


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_add_mtf_alignment()
    _migrate_add_ema_signal()
    _cleanup_monitored_setups_safety_valve()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
