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


class _Req:
    def __init__(self, headers, peer="10.0.0.1"):
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.client = type("C", (), {"host": peer})()


def test_direct_caller_cannot_pick_its_ip(monkeypatch):
    monkeypatch.setattr(ug, "PROXY_SHARED_SECRET", "s3cret")
    assert ug.client_ip(_Req({"X-Forwarded-For": "1.1.1.1, 203.0.113.7"})) == "203.0.113.7"
    assert ug.client_ip(_Req({"X-Forwarded-For": "1.1.1.1, 203.0.113.7",
                              "X-Proxy-Secret": "wrong"})) == "203.0.113.7"


def test_site_proxy_skips_its_own_hop(monkeypatch):
    monkeypatch.setattr(ug, "PROXY_SHARED_SECRET", "s3cret")
    req = _Req({"X-Forwarded-For": "6.6.6.6, 198.51.100.4, 34.1.2.3", "X-Proxy-Secret": "s3cret"})
    assert ug.client_ip(req) == "198.51.100.4"


def test_without_secret_the_proxy_keeps_working(monkeypatch):
    monkeypatch.setattr(ug, "PROXY_SHARED_SECRET", "")
    assert ug.client_ip(_Req({"X-Forwarded-For": "198.51.100.4, 34.1.2.3"})) == "198.51.100.4"
    assert ug.client_ip(_Req({"X-Forwarded-For": "198.51.100.4"})) == "198.51.100.4"
    assert ug.client_ip(_Req({})) == "10.0.0.1"
