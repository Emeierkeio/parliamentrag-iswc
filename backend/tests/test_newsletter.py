"""Newsletter opt-in: request schema and abuse limits (no Brevo calls)."""

import pytest

from app.routers import newsletter


@pytest.fixture(autouse=True)
def reset_windows():
    newsletter._hits.clear()
    yield
    newsletter._hits.clear()


def test_source_is_optional_and_whitelisted():
    assert newsletter.SubscribeRequest(email="a@b.it", consent=True).source is None
    assert newsletter.SubscribeRequest(email="a@b.it", consent=True, source="landing").source == "landing"
    with pytest.raises(ValueError):
        newsletter.SubscribeRequest(email="a@b.it", consent=True, source="tracking-pixel")


def test_consent_must_be_true():
    with pytest.raises(ValueError):
        newsletter.SubscribeRequest(email="a@b.it", consent=False)


def test_window_allows_up_to_limit():
    limit = (2, 60)
    assert not newsletter._over_limit("k", limit)
    assert not newsletter._over_limit("k", limit)
    assert newsletter._over_limit("k", limit)
    assert not newsletter._over_limit("other", limit)
