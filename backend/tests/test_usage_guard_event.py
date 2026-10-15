"""Raised query limits on the days of a live demo (QUERY_EVENT)."""
from datetime import date

from app.services import usage_guard as ug


def test_event_window(monkeypatch):
    monkeypatch.setattr(ug, "_EVENT", ug._parse_event("2026-10-24..2026-10-30:60:300"))
    assert ug.limits(date(2026, 10, 24)) == (60, 300)
    assert ug.limits(date(2026, 10, 30)) == (60, 300)
    assert ug.limits(date(2026, 10, 31)) == (ug.QUERY_LIMIT_PER_HOUR, ug.QUERY_LIMIT_PER_DAY)
    assert ug.limits(date(2026, 10, 23)) == (ug.QUERY_LIMIT_PER_HOUR, ug.QUERY_LIMIT_PER_DAY)


def test_bad_event_is_ignored():
    assert ug._parse_event("") is None
    assert ug._parse_event("24/10:60") is None
