from collections.abc import Generator
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Load local .env so DATABASE_URL is available in dev shells.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


_raw_db_url = os.getenv("DATABASE_URL")
DATABASE_URL = (_raw_db_url or "").strip()
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is required. Set it in the environment, e.g. "
        "postgresql+psycopg://user:pass@host:5432/dbname or sqlite:///./local.db"
    )


def _create_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if url.lower().startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine: Engine = _create_engine(DATABASE_URL)


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    return cfg


def init_db() -> None:
    from alembic import command

    import src.db.models  # noqa: F401 — register ORM tables (e.g. CandleCache)
    command.upgrade(_alembic_config(), "head")


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
