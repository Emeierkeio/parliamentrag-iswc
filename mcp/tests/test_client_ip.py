"""Rate limit key of the remote endpoint: the address Railway's edge saw."""
import server


def test_last_forwarded_entry_wins():
    assert server._client_ip("1.1.1.1, 203.0.113.7", "10.0.0.1") == "203.0.113.7"
    assert server._client_ip("", "10.0.0.1") == "10.0.0.1"
