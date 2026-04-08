from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


KEY_TABLES = [
    "monitored_setups",
    "alert_zones",
    "candle_cache",
    "signal_history",
    "scan_settings",
    "scan_settings_history",
]


def _table_counts_sqlalchemy(url: str) -> dict[str, int | None]:
    engine = create_engine(url)
    present = set(inspect(engine).get_table_names())
    counts: dict[str, int | None] = {}
    with engine.connect() as conn:
        for table in KEY_TABLES:
            if table not in present:
                counts[table] = None
                continue
            counts[table] = int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
    return counts


def _table_counts_sqlite(path: Path) -> dict[str, int | None]:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    present = {row[0] for row in cur.fetchall()}
    counts: dict[str, int | None] = {}
    for table in KEY_TABLES:
        if table not in present:
            counts[table] = None
            continue
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        counts[table] = int(cur.fetchone()[0])
    conn.close()
    return counts


def build_report(target_url: str, sources: list[Path]) -> dict[str, Any]:
    target = _table_counts_sqlalchemy(target_url)
    source_reports: list[dict[str, Any]] = []
    for source in sources:
        if source.exists():
            source_reports.append({"source": str(source), "counts": _table_counts_sqlite(source)})
        else:
            source_reports.append({"source": str(source), "missing_file": True})
    return {"target": target, "sources": source_reports}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate DB migration table coverage and counts.")
    parser.add_argument("--target-url", required=True, help="Target SQLAlchemy DB URL.")
    parser.add_argument("--source", action="append", default=[], help="SQLite source DB path. Can repeat.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    sources = [Path(p).resolve() for p in args.source]
    report = build_report(args.target_url, sources)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
