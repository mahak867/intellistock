"""Celery app: schedule and task registration."""

from __future__ import annotations

from backend.core import celery_app as mod


def test_beat_schedule_retrains_on_configured_interval():
    entry = mod.celery_app.conf.beat_schedule["retrain-models"]
    assert entry["task"] == "backend.core.celery_app.retrain_models"
    assert entry["schedule"] == mod.settings.RETRAIN_INTERVAL_HOURS * 3600


def test_tasks_are_registered():
    names = set(mod.celery_app.tasks)
    assert "backend.core.celery_app.retrain_model" in names
    assert "backend.core.celery_app.retrain_models" in names


def test_tickers_from_env(monkeypatch):
    monkeypatch.setenv("RETRAIN_TICKERS", " tcs, infy ,,")
    assert mod._tickers() == ["TCS", "INFY"]


def test_retrain_models_queues_one_task_per_ticker(monkeypatch):
    monkeypatch.setenv("RETRAIN_TICKERS", "TCS,INFY")
    queued = []
    monkeypatch.setattr(mod.retrain_model, "delay", lambda t: queued.append(t))
    assert mod.retrain_models() == ["TCS", "INFY"]
    assert queued == ["TCS", "INFY"]


def test_no_raw_string_sql_is_executed():
    """SQLAlchemy 2 rejects conn.execute('SELECT 1'); it must be text()."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    bad = [
        str(p)
        for p in root.rglob("*.py")
        if "tests" not in p.parts
        and re.search(r"\.execute\(\s*[\"']", p.read_text())
    ]
    assert bad == []
