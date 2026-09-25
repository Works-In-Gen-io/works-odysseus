"""Regression coverage for one-shot scheduled agent tasks."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import ScheduledTask
from src.task_scheduler import compute_next_run
from src.tools.system import do_manage_tasks


@pytest.fixture()
def task_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tasks.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", session)
    return session


def _read(session, task_id):
    db = session()
    try:
        return db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    finally:
        db.close()


def _create_args(**overrides):
    args = {
        "action": "create", "name": "one-shot", "prompt": "run once",
        "task_type": "llm", "trigger_type": "schedule", "schedule": "once",
    }
    args.update(overrides)
    return json.dumps(args)


@pytest.mark.asyncio
async def test_manage_create_once_persists_date_and_next_run(task_db):
    future = (datetime.utcnow() + timedelta(hours=1)).replace(microsecond=0).isoformat()
    out = await do_manage_tasks(_create_args(scheduled_date=future), owner="alice")
    task = _read(task_db, out["task_id"])
    assert out["exit_code"] == 0
    assert task.status == "active"
    assert task.scheduled_date == datetime.fromisoformat(future)
    assert task.next_run == task.scheduled_date


@pytest.mark.asyncio
@pytest.mark.parametrize("scheduled_date", [None, (datetime.utcnow() - timedelta(hours=1)).replace(microsecond=0).isoformat()])
async def test_manage_create_once_rejects_missing_or_past_date(task_db, scheduled_date):
    out = await do_manage_tasks(_create_args(**({} if scheduled_date is None else {"scheduled_date": scheduled_date})), owner="alice")
    assert out["exit_code"] == 1
    assert "scheduled_date" in out["error"] or "next_run" in out["error"]
    db = task_db()
    try:
        assert db.query(ScheduledTask).count() == 0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_manage_edit_once_recomputes_next_run_and_rejects_invalid(task_db):
    future = (datetime.utcnow() + timedelta(hours=1)).replace(microsecond=0).isoformat()
    out = await do_manage_tasks(_create_args(scheduled_date=future), owner="alice")
    task_id = out["task_id"]
    later = (datetime.utcnow() + timedelta(hours=2)).replace(microsecond=0).isoformat()
    edited = await do_manage_tasks(json.dumps({"action": "edit", "task_id": task_id, "scheduled_date": later}), owner="alice")
    assert edited["exit_code"] == 0
    task = _read(task_db, task_id)
    assert task.scheduled_date == datetime.fromisoformat(later)
    assert task.next_run == task.scheduled_date

    bad = await do_manage_tasks(json.dumps({"action": "edit", "task_id": task_id, "scheduled_date": "not-a-date"}), owner="alice")
    assert bad["exit_code"] == 1
    assert _read(task_db, task_id).next_run == task.scheduled_date


@pytest.mark.asyncio
async def test_manage_event_null_next_run_remains_valid(task_db):
    out = await do_manage_tasks(json.dumps({
        "action": "create", "name": "event", "prompt": "event", "task_type": "llm",
        "trigger_type": "event", "trigger_event": "message_sent", "trigger_count": 1,
    }), owner="alice")
    task = _read(task_db, out["task_id"])
    assert out["exit_code"] == 0
    assert task.status == "active"
    assert task.next_run is None


@pytest.mark.parametrize("schedule", ["daily", "weekly", "monthly"])
def test_recurring_schedules_still_materialize(schedule):
    assert compute_next_run(schedule, "09:00", scheduled_day=0, after=datetime(2026, 1, 1, 8, 0)) > datetime(2026, 1, 1, 8, 0)


@pytest.mark.asyncio
async def test_resume_rejects_once_without_future_next_run(task_db, monkeypatch):
    db = task_db()
    db.add(ScheduledTask(
        id="paused-once", owner="alice", name="paused", prompt="p", task_type="llm",
        trigger_type="schedule", schedule="once", status="paused",
    ))
    db.commit(); db.close()

    import routes.task.task_routes as task_routes
    monkeypatch.setattr(task_routes, "SessionLocal", task_db)
    monkeypatch.setattr(task_routes, "get_current_user", lambda request: "alice")
    router = task_routes.setup_task_routes(None)
    endpoint = next(r.endpoint for r in router.routes if getattr(r, "path", "").endswith("/{task_id}/resume"))
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await endpoint(SimpleNamespace(), "paused-once")
    assert exc.value.status_code == 400
    task = _read(task_db, "paused-once")
    assert task.status == "paused"
    assert task.next_run is None
