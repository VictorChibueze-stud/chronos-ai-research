from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db.models import AlertZone, MonitoredSetup, ScanSettings, ScanSettingsHistory, SignalHistory


def _parse_datetime(raw: Any) -> datetime | None:
    if raw is None or isinstance(raw, datetime):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    return {}


@dataclass
class BackfillStats:
    setups_inserted: int = 0
    setups_updated: int = 0
    zones_inserted: int = 0
    zones_updated: int = 0
    signals_inserted: int = 0
    scan_settings_inserted: int = 0
    scan_settings_history_inserted: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "setups_inserted": self.setups_inserted,
            "setups_updated": self.setups_updated,
            "zones_inserted": self.zones_inserted,
            "zones_updated": self.zones_updated,
            "signals_inserted": self.signals_inserted,
            "scan_settings_inserted": self.scan_settings_inserted,
            "scan_settings_history_inserted": self.scan_settings_history_inserted,
        }


def _fetch_sqlite_rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    if cur.fetchone() is None:
        return []
    cur.execute(f"SELECT * FROM {table}")
    return cur.fetchall()


def _upsert_monitored_setups(
    db: Session,
    source_rows: list[sqlite3.Row],
    dry_run: bool,
    stats: BackfillStats,
) -> dict[int, int]:
    by_key: dict[tuple[str, str], sqlite3.Row] = {}
    for row in source_rows:
        key = (str(row["symbol"]).upper(), str(row["htf_timeframe"]))
        old = by_key.get(key)
        if old is None:
            by_key[key] = row
            continue
        old_updated = _parse_datetime(old["updated_at"]) or datetime.min
        new_updated = _parse_datetime(row["updated_at"]) or datetime.min
        if new_updated >= old_updated:
            by_key[key] = row

    source_to_target_id: dict[int, int] = {}
    for row in by_key.values():
        symbol = str(row["symbol"]).upper()
        timeframe = str(row["htf_timeframe"])
        existing = (
            db.query(MonitoredSetup)
            .filter(MonitoredSetup.symbol == symbol, MonitoredSetup.htf_timeframe == timeframe)
            .order_by(MonitoredSetup.updated_at.desc(), MonitoredSetup.id.desc())
            .first()
        )

        payload = {
            "symbol": symbol,
            "htf_timeframe": timeframe,
            "htf_trend_direction": str(row["htf_trend_direction"]),
            "current_phase": row["current_phase"],
            "status": str(row["status"]),
            "ema_signal": row["ema_signal"],
            "trend_score": float(row["trend_score"]),
            "structural_state_json": _parse_json(row["structural_state_json"]),
            "mtf_alignment": _parse_json(row["mtf_alignment"]),
            "last_checked_at": _parse_datetime(row["last_checked_at"]) or datetime.utcnow(),
            "created_at": _parse_datetime(row["created_at"]) or datetime.utcnow(),
            "updated_at": _parse_datetime(row["updated_at"]) or datetime.utcnow(),
        }

        if existing is None:
            stats.setups_inserted += 1
            if not dry_run:
                setup = MonitoredSetup(**payload)
                db.add(setup)
                db.flush()
                source_to_target_id[int(row["id"])] = int(setup.id)
        else:
            stats.setups_updated += 1
            if not dry_run:
                for key, value in payload.items():
                    setattr(existing, key, value)
                db.flush()
                source_to_target_id[int(row["id"])] = int(existing.id)

    if not dry_run:
        db.commit()
    return source_to_target_id


def _upsert_alert_zones(
    db: Session,
    source_rows: list[sqlite3.Row],
    source_to_target_id: dict[int, int],
    dry_run: bool,
    stats: BackfillStats,
) -> None:
    for row in source_rows:
        source_setup_id = int(row["setup_id"])
        target_setup_id = source_to_target_id.get(source_setup_id)
        if target_setup_id is None:
            continue

        zone_type = str(row["zone_type"])
        depth = int(row["depth"]) if row["depth"] is not None else None
        price_high = float(row["price_high"])
        price_low = float(row["price_low"])
        watch_condition = str(row["watch_condition"])
        is_manual_override = bool(row["is_manual_override"])

        existing = (
            db.query(AlertZone)
            .filter(
                AlertZone.setup_id == target_setup_id,
                AlertZone.zone_type == zone_type,
                AlertZone.depth == depth,
                AlertZone.price_high == price_high,
                AlertZone.price_low == price_low,
                AlertZone.watch_condition == watch_condition,
                AlertZone.is_manual_override == is_manual_override,
            )
            .first()
        )

        if existing is None:
            stats.zones_inserted += 1
            if not dry_run:
                db.add(
                    AlertZone(
                        setup_id=target_setup_id,
                        zone_type=zone_type,
                        depth=depth,
                        price_high=price_high,
                        price_low=price_low,
                        is_active=bool(row["is_active"]),
                        watch_condition=watch_condition,
                        is_manual_override=is_manual_override,
                    )
                )
        else:
            stats.zones_updated += 1
            if not dry_run:
                existing.is_active = bool(row["is_active"])

    if not dry_run:
        db.commit()


def _upsert_signal_history(
    db: Session,
    source_rows: list[sqlite3.Row],
    dry_run: bool,
    stats: BackfillStats,
) -> None:
    for row in source_rows:
        symbol = str(row["symbol"]).upper()
        timeframe = str(row["timeframe"])
        signal = str(row["signal"])
        emitted_at = _parse_datetime(row["emitted_at"])
        if emitted_at is None:
            continue

        exists = (
            db.query(SignalHistory)
            .filter(
                SignalHistory.symbol == symbol,
                SignalHistory.timeframe == timeframe,
                SignalHistory.signal == signal,
                SignalHistory.emitted_at == emitted_at,
            )
            .first()
        )
        if exists is not None:
            continue

        stats.signals_inserted += 1
        if not dry_run:
            db.add(
                SignalHistory(
                    symbol=symbol,
                    timeframe=timeframe,
                    signal=signal,
                    trend_direction=row["trend_direction"],
                    trend_score=float(row["trend_score"]) if row["trend_score"] is not None else None,
                    emitted_at=emitted_at,
                )
            )

    if not dry_run:
        db.commit()


def _upsert_scan_settings(
    db: Session,
    settings_rows: list[sqlite3.Row],
    history_rows: list[sqlite3.Row],
    dry_run: bool,
    stats: BackfillStats,
) -> None:
    for row in settings_rows:
        scope = str(row["scope"])
        exists = db.query(ScanSettings).filter(ScanSettings.scope == scope).one_or_none()
        if exists is not None:
            continue
        stats.scan_settings_inserted += 1
        if not dry_run:
            db.add(
                ScanSettings(
                    scope=scope,
                    settings_json=_parse_json(row["settings_json"]),
                    updated_at=_parse_datetime(row["updated_at"]) or datetime.utcnow(),
                )
            )

    if not dry_run:
        db.commit()

    for row in history_rows:
        scope = str(row["scope"])
        created_at = _parse_datetime(row["created_at"])
        if created_at is None:
            continue
        exists = (
            db.query(ScanSettingsHistory)
            .filter(
                ScanSettingsHistory.scope == scope,
                ScanSettingsHistory.created_at == created_at,
            )
            .first()
        )
        if exists is not None:
            continue
        stats.scan_settings_history_inserted += 1
        if not dry_run:
            db.add(
                ScanSettingsHistory(
                    scope=scope,
                    settings_json=_parse_json(row["settings_json"]),
                    created_at=created_at,
                )
            )

    if not dry_run:
        db.commit()


def backfill_from_sources(
    target_database_url: str,
    source_paths: list[Path],
    dry_run: bool = True,
) -> dict[str, Any]:
    engine = create_engine(target_database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    stats = BackfillStats()
    per_source: list[dict[str, Any]] = []

    for source_path in source_paths:
        if not source_path.exists():
            per_source.append({"source": str(source_path), "skipped": "missing_file"})
            continue

        conn = sqlite3.connect(source_path)
        conn.row_factory = sqlite3.Row
        db = SessionLocal()
        source_stats_before = stats.to_dict()
        try:
            setup_rows = _fetch_sqlite_rows(conn, "monitored_setups")
            zone_rows = _fetch_sqlite_rows(conn, "alert_zones")
            signal_rows = _fetch_sqlite_rows(conn, "signal_history")
            settings_rows = _fetch_sqlite_rows(conn, "scan_settings")
            settings_history_rows = _fetch_sqlite_rows(conn, "scan_settings_history")

            source_to_target = _upsert_monitored_setups(db, setup_rows, dry_run=dry_run, stats=stats)
            _upsert_alert_zones(db, zone_rows, source_to_target, dry_run=dry_run, stats=stats)
            _upsert_signal_history(db, signal_rows, dry_run=dry_run, stats=stats)
            _upsert_scan_settings(
                db,
                settings_rows=settings_rows,
                history_rows=settings_history_rows,
                dry_run=dry_run,
                stats=stats,
            )
        finally:
            db.close()
            conn.close()

        source_stats_after = stats.to_dict()
        source_delta = {
            key: source_stats_after[key] - source_stats_before[key]
            for key in source_stats_after
        }
        per_source.append({"source": str(source_path), "delta": source_delta})

    return {"dry_run": dry_run, "stats": stats.to_dict(), "per_source": per_source}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill scanner-state tables from SQLite to target DB")
    parser.add_argument(
        "--target-url",
        default=(os.getenv("DATABASE_URL") or "").strip(),
        help="Target SQLAlchemy DB URL (defaults to DATABASE_URL).",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="SQLite source path. Can be repeated.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Default is dry-run.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if not args.target_url:
        raise RuntimeError("Target URL is required. Set DATABASE_URL or pass --target-url.")

    default_sources = [ROOT / "ikenga.db", ROOT / "data" / "chronos.db"]
    source_paths = [Path(p).resolve() for p in args.source] if args.source else default_sources
    report = backfill_from_sources(
        target_database_url=args.target_url,
        source_paths=source_paths,
        dry_run=not args.apply,
    )
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
