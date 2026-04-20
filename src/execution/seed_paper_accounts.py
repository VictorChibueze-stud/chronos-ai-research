"""
Seed the three default paper accounts.
Safe to rerun — skips if account name already exists.
Backfills universe on existing accounts that have null universe.
Usage: python -m src.execution.seed_paper_accounts
"""
from datetime import datetime, timezone

from src.db.models import PaperAccount
from src.db.session import SessionLocal

DEFAULT_ACCOUNTS = [
    {
        "name": "Multi-Asset",
        "account_type": "deriv_non_synthetic",
        "balance_usd": 100000.0,
        "initial_balance_usd": 100000.0,
        "universe": "multi_asset",
    },
    {
        "name": "Synthetic",
        "account_type": "deriv_synthetic",
        "balance_usd": 100000.0,
        "initial_balance_usd": 100000.0,
        "universe": "synthetic",
    },
    {
        "name": "Crypto",
        "account_type": "binance",
        "balance_usd": 100000.0,
        "initial_balance_usd": 100000.0,
        "universe": "crypto",
    },
]

# Legacy account names that should be renamed to universe-aligned names.
NAME_UPDATES = {
    "Deriv Non-Synthetic": "Multi-Asset",
    "Deriv Synthetic": "Synthetic",
    "Binance": "Crypto",
}


def seed_paper_accounts() -> None:
    db = SessionLocal()
    inserted = 0
    skipped = 0
    backfilled = 0
    renamed = 0
    try:
        # Rename legacy accounts before the insert pass so the
        # name-uniqueness check below picks them up correctly.
        for old_name, new_name in NAME_UPDATES.items():
            row = (
                db.query(PaperAccount)
                .filter(PaperAccount.name == old_name)
                .first()
            )
            if row is not None:
                row.name = new_name
                renamed += 1
        if renamed:
            db.commit()

        for acct in DEFAULT_ACCOUNTS:
            existing = (
                db.query(PaperAccount)
                .filter(PaperAccount.name == acct["name"])
                .first()
            )
            if existing is not None:
                if existing.universe is None:
                    existing.universe = acct.get("universe")
                    backfilled += 1
                skipped += 1
                continue
            db.add(
                PaperAccount(
                    name=acct["name"],
                    account_type=acct["account_type"],
                    balance_usd=acct["balance_usd"],
                    initial_balance_usd=acct["initial_balance_usd"],
                    universe=acct.get("universe"),
                )
            )
            inserted += 1
        db.commit()
        print(
            f"Paper accounts: {inserted} inserted, "
            f"{skipped} already exist, "
            f"{backfilled} universe backfilled, "
            f"{renamed} renamed"
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed_paper_accounts()
