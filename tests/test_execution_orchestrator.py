from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import ExecutionOrder, SystemSettings
from src.db.session import Base
from src.execution.contracts import NormalizedOrderIntent, OrderStatus, ProviderId
from src.execution.orchestrator import ExecutionOrchestrator


@pytest.fixture()
def db_session(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    sess = Session()
    sess.add(SystemSettings(killswitch_active=False))
    sess.commit()
    monkeypatch.setenv("EXECUTION_ENABLED", "1")
    monkeypatch.setenv("EXECUTION_PROVIDER", "stub")
    yield sess
    sess.close()


def test_orchestrator_stub_fill(db_session):
    orch = ExecutionOrchestrator(db_session)
    intent = NormalizedOrderIntent(symbol="R_10", side="long", stake_amount=1.0, provider=ProviderId.DERIV)
    resp = orch.submit(intent)
    assert resp.ok is True
    assert resp.status == OrderStatus.FILLED
    row = db_session.query(ExecutionOrder).filter_by(client_order_id=intent.client_order_id).one()
    assert row.provider == "stub"
    assert row.status == "filled"


def test_orchestrator_idempotent(db_session):
    orch = ExecutionOrchestrator(db_session)
    intent = NormalizedOrderIntent(symbol="R_10", side="long", stake_amount=1.0, provider=ProviderId.DERIV)
    r1 = orch.submit(intent)
    r2 = orch.submit(intent)
    assert r1.ok and r2.ok
    assert db_session.query(ExecutionOrder).count() == 1


def test_orchestrator_killswitch(db_session):
    s = db_session.query(SystemSettings).one()
    s.killswitch_active = True
    db_session.commit()
    orch = ExecutionOrchestrator(db_session)
    intent = NormalizedOrderIntent(symbol="R_10", side="long", stake_amount=1.0)
    resp = orch.submit(intent)
    assert resp.ok is False
    assert resp.status == OrderStatus.REJECTED
