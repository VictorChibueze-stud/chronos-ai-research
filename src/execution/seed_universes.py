"""
Seed the three default universe settings.
Safe to rerun — skips if universe_name exists.
Usage: python -m src.execution.seed_universes
"""
from datetime import datetime, timezone

from src.db.session import SessionLocal
from src.db.models import UniverseSettings

DEFAULT_UNIVERSES = [
    {
        "universe_name": "multi_asset",
        "capacity": 50,
        "rank_frequency": "weekly",
        "refresh_offset_hours": 0,
        "refresh_interval_hours": 4,
        "top_n": 200,
        "non_top_n_depth": "global_and_prime",
        "category_min_slots_json": {
            "forex": 30,
            "indices": 15,
            "commodity": 10,
            "equities": 80,
        },
    },
    {
        "universe_name": "synthetic",
        "capacity": 30,
        "rank_frequency": "daily",
        "refresh_offset_hours": 1,
        "refresh_interval_hours": 4,
        "top_n": 100,
        "non_top_n_depth": "global_and_prime",
        "category_min_slots_json": {
            "synthetic": 50,
        },
    },
    {
        "universe_name": "crypto",
        "capacity": 20,
        "rank_frequency": "daily",
        "refresh_offset_hours": 2,
        "refresh_interval_hours": 4,
        "top_n": 100,
        "non_top_n_depth": "global_only",
        "category_min_slots_json": {
            "crypto": 50,
        },
    },
]


def seed_universes() -> None:
    db = SessionLocal()
    inserted = 0
    skipped = 0
    try:
        for u in DEFAULT_UNIVERSES:
            existing = (
                db.query(UniverseSettings)
                .filter(
                    UniverseSettings.universe_name == u["universe_name"]
                )
                .first()
            )
            if existing is not None:
                skipped += 1
                continue
            db.add(UniverseSettings(**u))
            inserted += 1
        db.commit()
        print(
            f"Universes: {inserted} inserted, "
            f"{skipped} already exist"
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed_universes()
