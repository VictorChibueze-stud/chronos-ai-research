"""
Run once to populate contract_specs table from seed data.
Safe to rerun — uses upsert (update if exists, insert if not).
Usage: python -m src.execution.seed_contract_specs
"""
from datetime import datetime, timezone

from src.db.models import ContractSpec
from src.db.session import SessionLocal
from src.execution.contract_spec_seed import CONTRACT_SPEC_SEED


def seed_contract_specs() -> None:
    db = SessionLocal()
    inserted = 0
    updated = 0
    try:
        for spec in CONTRACT_SPEC_SEED:
            sym = spec["symbol"].upper()
            existing = (
                db.query(ContractSpec)
                .filter(ContractSpec.symbol == sym)
                .first()
            )
            now = datetime.now(timezone.utc)
            if existing is None:
                db.add(
                    ContractSpec(
                        symbol=sym,
                        asset_class=spec["asset_class"],
                        pip_size=spec["pip_size"],
                        point_value=spec["point_value"],
                        contract_size=spec["contract_size"],
                        lot_size_min=spec["lot_size_min"],
                        lot_size_max=spec["lot_size_max"],
                        lot_size_step=spec["lot_size_step"],
                        quote_currency=spec.get("quote_currency"),
                        base_currency=spec.get("base_currency"),
                        is_crypto=spec.get("is_crypto", False),
                        notes=spec.get("notes"),
                        last_fetched_at=now,
                        updated_at=now,
                    )
                )
                inserted += 1
            else:
                existing.asset_class = spec["asset_class"]
                existing.pip_size = spec["pip_size"]
                existing.point_value = spec["point_value"]
                existing.contract_size = spec["contract_size"]
                existing.lot_size_min = spec["lot_size_min"]
                existing.lot_size_max = spec["lot_size_max"]
                existing.lot_size_step = spec["lot_size_step"]
                existing.quote_currency = spec.get("quote_currency")
                existing.base_currency = spec.get("base_currency")
                existing.is_crypto = spec.get("is_crypto", False)
                existing.notes = spec.get("notes")
                existing.last_fetched_at = now
                existing.updated_at = now
                updated += 1
        db.commit()
        print(f"Contract specs seeded: {inserted} inserted, {updated} updated")
    finally:
        db.close()


if __name__ == "__main__":
    seed_contract_specs()
