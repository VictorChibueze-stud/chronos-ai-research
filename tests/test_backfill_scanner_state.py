from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

from scripts.backfill_scanner_state import backfill_from_sources
from src.db.session import Base


def _create_source_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE monitored_setups (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            htf_timeframe TEXT NOT NULL,
            htf_trend_direction TEXT NOT NULL,
            current_phase TEXT,
            status TEXT NOT NULL,
            ema_signal TEXT,
            trend_score REAL NOT NULL,
            structural_state_json TEXT NOT NULL,
            mtf_alignment TEXT,
            last_checked_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE alert_zones (
            id INTEGER PRIMARY KEY,
            setup_id INTEGER NOT NULL,
            zone_type TEXT NOT NULL,
            depth INTEGER,
            price_high REAL NOT NULL,
            price_low REAL NOT NULL,
            is_active INTEGER NOT NULL,
            watch_condition TEXT NOT NULL,
            is_manual_override INTEGER NOT NULL
        );
        CREATE TABLE signal_history (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            signal TEXT NOT NULL,
            trend_direction TEXT,
            trend_score REAL,
            emitted_at TEXT NOT NULL
        );
        CREATE TABLE scan_settings (
            id INTEGER PRIMARY KEY,
            scope TEXT NOT NULL,
            settings_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE scan_settings_history (
            id INTEGER PRIMARY KEY,
            scope TEXT NOT NULL,
            settings_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        """
        INSERT INTO monitored_setups
        (id, symbol, htf_timeframe, htf_trend_direction, current_phase, status, ema_signal, trend_score,
         structural_state_json, mtf_alignment, last_checked_at, created_at, updated_at)
        VALUES
        (1, 'BTCUSDT', '1h', 'up', 'retracement', 'MONITORING', 'LONG', 88.5,
         '{"max_depth_reached": 2}', '{"1h":"up"}', ?, ?, ?)
        """,
        (now, now, now),
    )
    cur.execute(
        """
        INSERT INTO alert_zones
        (id, setup_id, zone_type, depth, price_high, price_low, is_active, watch_condition, is_manual_override)
        VALUES (1, 1, 'MANUAL_OVERRIDE', 1, 100.0, 90.0, 1, 'inside_zone', 1)
        """
    )
    cur.execute(
        """
        INSERT INTO signal_history
        (id, symbol, timeframe, signal, trend_direction, trend_score, emitted_at)
        VALUES (1, 'BTCUSDT', '1h', 'LONG', 'up', 88.5, ?)
        """,
        (now,),
    )
    cur.execute(
        """
        INSERT INTO scan_settings
        (id, scope, settings_json, updated_at)
        VALUES (1, 'global', '{"brokers":["binance","deriv"],"binance_top_n":350}', ?)
        """,
        (now,),
    )
    cur.execute(
        """
        INSERT INTO scan_settings_history
        (id, scope, settings_json, created_at)
        VALUES (1, 'global', '{"brokers":["binance","deriv"],"binance_top_n":350}', ?)
        """,
        (now,),
    )
    conn.commit()
    conn.close()


def test_backfill_is_idempotent_and_preserves_zone_integrity(tmp_path: Path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _create_source_db(source)

    target_url = f"sqlite:///{target.as_posix()}"
    target_engine = create_engine(target_url)
    Base.metadata.create_all(bind=target_engine)

    first = backfill_from_sources(target_database_url=target_url, source_paths=[source], dry_run=False)
    second = backfill_from_sources(target_database_url=target_url, source_paths=[source], dry_run=False)

    assert first["stats"]["setups_inserted"] == 1
    assert first["stats"]["zones_inserted"] == 1
    assert first["stats"]["signals_inserted"] == 1
    assert first["stats"]["scan_settings_inserted"] == 1
    assert first["stats"]["scan_settings_history_inserted"] == 1

    # On second run we may update existing rows, but we should not duplicate them.
    assert second["stats"]["setups_inserted"] == 0
    assert second["stats"]["zones_inserted"] == 0
    assert second["stats"]["signals_inserted"] == 0
    assert second["stats"]["scan_settings_inserted"] == 0
    assert second["stats"]["scan_settings_history_inserted"] == 0

    with target_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM monitored_setups")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM alert_zones")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM signal_history")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM scan_settings")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM scan_settings_history")).scalar_one() == 1

        orphan_count = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM alert_zones az
                LEFT JOIN monitored_setups ms ON ms.id = az.setup_id
                WHERE ms.id IS NULL
                """
            )
        ).scalar_one()
        assert orphan_count == 0
