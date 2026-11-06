"""Alert checking: rules fire on the latest close, deliver only with real data, never twice, never across users."""
import asyncio
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core import database
from backend.core.config import settings
from backend.data import providers
from backend.models.db_models import AlertRule, Base, Feedback, User
from backend.services import alert_service as S


def _frame(last_close=100.0, last_range=0.02, n=120):
    idx = pd.bdate_range(end="2026-10-30", periods=n)
    c = np.full(n, 100.0)
    c[-1] = last_close
    return pd.DataFrame({"open": c, "high": c * (1 + 0.005), "low": c * (1 - 0.005), "close": c, "volume": 1000.0}, index=idx).assign(
        high=lambda d: np.where(d.index == d.index[-1], d.close * (1 + last_range / 2), d.high),
        low=lambda d: np.where(d.index == d.index[-1], d.close * (1 - last_range / 2), d.low))


class Sender:
    sent: list = []

    def __init__(self, token, chat):
        self.chat = chat

    def send(self, text):
        Sender.sent.append((self.chat, text))
        return True


@pytest.fixture
def db(tmp_path, monkeypatch):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")

    async def setup():
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    monkeypatch.setattr(database, "AsyncSessionFactory", async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False))
    monkeypatch.setattr(providers, "licensed", lambda: True)
    Sender.sent = []
    yield eng
    asyncio.run(eng.dispose())


def _prices(monkeypatch, df, source="nse"):
    monkeypatch.setattr(providers, "get_prices", lambda sym, days=700: providers.Prices(df, source, None))


async def _seed(rules, chat="123456"):
    async with database.get_session() as s:
        u1 = User(email="a@example.com", full_name="A", hashed_password="x", telegram_chat_id=chat)
        u2 = User(email="b@example.com", full_name="B", hashed_password="x")
        s.add_all([u1, u2])
        await s.flush()
        for owner, ticker, kind, val in rules:
            s.add(AlertRule(user_id=(u1 if owner == "a" else u2).id, ticker=ticker, alert_type=kind, price_target=val))
        return u1.id, u2.id


async def _rules():
    from sqlalchemy import select
    async with database.get_session() as s:
        return (await s.execute(select(AlertRule))).scalars().all()


def test_snapshot_uses_prior_days_for_normal_range():
    snap = S.snapshot(_frame(last_range=0.08))
    assert snap["price"] == 100.0 and snap["forecast_daily_vol"] > 0
    assert snap["day_high"] / snap["day_low"] > 1.07


def test_price_alert_fires_delivers_and_switches_off(db, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "tok")
    _prices(monkeypatch, _frame(105.0))
    asyncio.run(_seed([("a", "TCS", "price_above", 104.0), ("a", "TCS", "price_below", 90.0)]))
    out = asyncio.run(S.check_alerts(make_sender=Sender))
    assert out["checked"] == 2 and len(out["fired"]) == 1
    assert out["fired"][0]["delivered"] is True and Sender.sent[0][0] == "123456"
    assert "above your level" in Sender.sent[0][1] and "placeholder" not in Sender.sent[0][1]
    rules = {r.alert_type: r for r in asyncio.run(_rules())}
    assert rules["price_above"].is_active is False and rules["price_above"].trigger_count == 1
    assert rules["price_above"].last_message and rules["price_below"].is_active is True
    again = asyncio.run(S.check_alerts(make_sender=Sender))
    assert again["fired"] == [] and len(Sender.sent) == 1  # the fired rule is off; no repeat


def test_placeholder_prices_are_labelled_and_never_sent(db, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "tok")
    _prices(monkeypatch, _frame(105.0), source="synthetic")
    asyncio.run(_seed([("a", "TCS", "price_above", 104.0)]))
    out = asyncio.run(S.check_alerts(make_sender=Sender))
    assert out["real_data"] is False and out["fired"][0]["delivered"] is None
    assert out["fired"][0]["message"].startswith("[placeholder prices") and Sender.sent == []


def test_unlicensed_data_is_not_sent(db, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(providers, "licensed", lambda: False)
    _prices(monkeypatch, _frame(105.0))
    asyncio.run(_seed([("a", "TCS", "price_above", 104.0)]))
    out = asyncio.run(S.check_alerts(make_sender=Sender))
    assert out["fired"][0]["delivered"] is None and Sender.sent == []


def test_no_chat_id_or_no_token_means_in_app_only(db, monkeypatch):
    _prices(monkeypatch, _frame(105.0))
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None)
    asyncio.run(_seed([("a", "TCS", "price_above", 104.0), ("b", "TCS", "price_above", 104.0)]))
    out = asyncio.run(S.check_alerts(make_sender=Sender))
    assert len(out["fired"]) == 2 and all(f["delivered"] is None for f in out["fired"]) and Sender.sent == []


def test_failed_send_is_reported_not_raised(db, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "tok")
    _prices(monkeypatch, _frame(105.0))

    class Boom:
        def __init__(self, *a): pass
        def send(self, t): raise RuntimeError("network")

    asyncio.run(_seed([("a", "TCS", "price_above", 104.0)]))
    out = asyncio.run(S.check_alerts(make_sender=Boom))
    assert out["fired"][0]["delivered"] is False


def test_vol_spike_fires_once_per_day(db, monkeypatch):
    _prices(monkeypatch, _frame(100.0, last_range=0.08))  # 8% range vs normal 1%
    asyncio.run(_seed([("a", "TCS", "vol_spike", 3.0)]))
    first = asyncio.run(S.check_alerts(make_sender=Sender))
    second = asyncio.run(S.check_alerts(make_sender=Sender))
    assert len(first["fired"]) == 1 and "normal daily range" in first["fired"][0]["message"]
    assert second["fired"] == []
    assert asyncio.run(_rules())[0].is_active is True  # vol alerts stay armed


def test_quiet_day_does_not_fire_vol_spike(db, monkeypatch):
    _prices(monkeypatch, _frame(100.0, last_range=0.01))
    asyncio.run(_seed([("a", "TCS", "vol_spike", 2.0)]))
    assert asyncio.run(S.check_alerts(make_sender=Sender))["fired"] == []


def test_missing_prices_are_skipped_with_reason(db, monkeypatch):
    def no(sym, days=700):
        raise providers.NoData("No data for XYZ in the local store.")
    monkeypatch.setattr(providers, "get_prices", no)
    asyncio.run(_seed([("a", "XYZ", "price_above", 1.0)]))
    out = asyncio.run(S.check_alerts())
    assert out["fired"] == [] and out["skipped"][0]["reason"].startswith("No data")


def test_check_only_touches_the_asking_user(db, monkeypatch):
    _prices(monkeypatch, _frame(105.0))
    a, b = asyncio.run(_seed([("a", "TCS", "price_above", 104.0), ("b", "TCS", "price_above", 104.0)]))
    out = asyncio.run(S.check_alerts(user_id=b, make_sender=Sender))
    assert out["checked"] == 1
    by_owner = {r.user_id: r for r in asyncio.run(_rules())}
    assert by_owner[b].trigger_count == 1 and by_owner[a].trigger_count == 0


def test_legacy_signal_rules_are_ignored(db, monkeypatch):
    _prices(monkeypatch, _frame(105.0))
    asyncio.run(_seed([("a", "TCS", "signal", None)]))
    assert asyncio.run(S.check_alerts())["checked"] == 0


def test_beat_schedule_checks_alerts():
    from backend.core import celery_app as mod
    assert mod.celery_app.conf.beat_schedule["check-alerts"]["schedule"] == settings.ALERT_CHECK_MINUTES * 60
    assert "backend.core.celery_app.check_alerts" in set(mod.celery_app.tasks)


def test_request_schema():
    from backend.api.routes.users import AlertAddRequest, FeedbackRequest, UpdateProfileRequest
    AlertAddRequest(ticker="TCS", alert_type="price_above", price_target=4000)
    AlertAddRequest(ticker="TCS", alert_type="vol_spike", price_target=2)
    for bad in [dict(alert_type="signal", price_target=1), dict(alert_type="price_above"), dict(alert_type="vol_spike", price_target=0.5),
                dict(alert_type="vol_spike", price_target=50), dict(alert_type="price_above", price_target=float("inf")),
                dict(alert_type="price_above", price_target=1e12)]:
        with pytest.raises(Exception):
            AlertAddRequest(ticker="TCS", **bad)
    assert UpdateProfileRequest(telegram_chat_id="").telegram_chat_id == ""
    assert UpdateProfileRequest(telegram_chat_id="-1001234567890").telegram_chat_id
    for bad in ["abc", "12", "1 2 3 4 5", "123456; drop"]:
        with pytest.raises(Exception):
            UpdateProfileRequest(telegram_chat_id=bad)
    FeedbackRequest(category="bug", message="The chart is blank")
    for bad in [dict(category="bug", message="hi"), dict(category="x", message="long enough"), dict(category="bug", message="a" * 2001),
                dict(category="bug", message="null \x00 byte")]:
        with pytest.raises(Exception):
            FeedbackRequest(**bad)


def test_feedback_row_roundtrip(db):
    async def go():
        async with database.get_session() as s:
            s.add(Feedback(category="data", message="Price looks wrong", page="/portfolio"))
    asyncio.run(go())


def test_delete_and_rearm_work_on_sqlite_with_uuid_path_ids(db):
    """Regression: a uuid.UUID path id reached the UUID(as_uuid=False) column and the demo database (SQLite) answered 500."""
    import uuid
    from fastapi import HTTPException
    from backend.api.routes import users as U
    from backend.models.db_models import PortfolioEntry, WatchlistItem
    from backend.services.stock_service import StockService

    async def go():
        a, b = await _seed([("a", "TCS", "price_above", 100.0)])
        async with database.get_session() as s:
            s.add(PortfolioEntry(user_id=a, ticker="TCS", exchange="NSE", quantity=1, avg_buy_price=1, buy_date=datetime.now(timezone.utc)))
            s.add(WatchlistItem(user_id=a, ticker="TCS", exchange="NSE"))
        rule = (await _rules())[0]
        me, other = {"sub": a}, {"sub": b}
        with pytest.raises(HTTPException) as e:
            await U.rearm_alert(uuid.UUID(rule.id), other)
        assert e.value.status_code == 404
        with pytest.raises(HTTPException) as e:
            await U.remove_alert(uuid.UUID(rule.id), other)
        assert e.value.status_code == 404
        rule.is_active = False
        assert (await U.rearm_alert(uuid.UUID(rule.id), me))["id"] == rule.id
        await U.remove_alert(uuid.UUID(rule.id), me)
        assert await _rules() == []
        from sqlalchemy import select
        async with database.get_session() as s:
            pe = (await s.execute(select(PortfolioEntry))).scalars().one()
            wi = (await s.execute(select(WatchlistItem))).scalars().one()
        await U.remove_portfolio_entry(uuid.UUID(pe.id), me)
        assert await StockService.remove_watchlist(str(uuid.UUID(wi.id)), a) is True

    asyncio.run(go())
