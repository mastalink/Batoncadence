"""Local-Only must not silently enable public ntfy.sh.

Growth G1: a default NTFY_TOPIC of mco-events made get_ntfy_config() look
enabled, printed 'NTFY notifier enabled -> https://ntfy.sh/mco-events', and
POSTed job events to a shared public topic. Blank topic = off.
"""
from __future__ import annotations

import mco.notifiers.ntfy as ntfy_mod
import pytest


class _Cfg:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values[key] if key in self.values else default


@pytest.fixture(autouse=True)
def _clear_ntfy_state():
    ntfy_mod._last_sent.clear()
    ntfy_mod._push_sends.clear()
    ntfy_mod._batched.clear()


def test_topic_unset_means_off(monkeypatch):
    monkeypatch.setattr(ntfy_mod, "get_config", lambda: _Cfg())
    cfg = ntfy_mod.get_ntfy_config()
    assert cfg["topic"] == ""
    assert cfg["server"] == "https://ntfy.sh"


def test_notify_does_not_post_when_topic_unset(monkeypatch):
    monkeypatch.setattr(ntfy_mod, "get_config", lambda: _Cfg())
    posted = []
    monkeypatch.setattr(
        ntfy_mod.requests,
        "post",
        lambda *a, **k: posted.append((a, k)),
    )
    assert ntfy_mod.notify("hello") is False
    ntfy_mod.notify_job_created("j1", "title", "claude")
    ntfy_mod.notify_gateway_startup({"host": "127.0.0.1", "port": 18789, "pid": 1})
    assert posted == []


def test_notify_posts_when_topic_set(monkeypatch):
    monkeypatch.setattr(
        ntfy_mod, "get_config", lambda: _Cfg({"NTFY_TOPIC": "v7Jk2pQ9xN4mR8sT6wY3cF5hL1dB0zGa"})
    )

    class _Resp:
        def raise_for_status(self):
            return None

    posted = []

    def _post(url, **kwargs):
        posted.append(url)
        return _Resp()

    monkeypatch.setattr(ntfy_mod.requests, "post", _post)
    assert ntfy_mod.notify("hello") is True
    assert posted == ["https://ntfy.sh/v7Jk2pQ9xN4mR8sT6wY3cF5hL1dB0zGa"]


def test_short_or_role_derived_topics_fail_closed(monkeypatch):
    posted = []
    monkeypatch.setattr(ntfy_mod.requests, "post", lambda *a, **k: posted.append(a))
    for topic in ("mco-codex", "codex", "claude-beast", "mco-" + "x" * 40, "short-private"):
        monkeypatch.setattr(ntfy_mod, "get_config", lambda topic=topic: _Cfg({"NTFY_TOPIC": topic}))
        assert ntfy_mod.get_ntfy_config()["topic"] == ""
        assert ntfy_mod.send_test_push() is False
    assert posted == []


def test_caller_cannot_override_destination_or_payload(monkeypatch):
    topic = "A9vK2xP7mQ4sT8wY5cF1hL6dB3zR0nGj"
    monkeypatch.setattr(ntfy_mod, "get_config", lambda: _Cfg({"NTFY_TOPIC": topic}))
    posted = []

    class _Resp:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(ntfy_mod.requests, "post", lambda url, **kw: posted.append((url, kw)) or _Resp())
    assert ntfy_mod.notify("household secret", title="mco-codex", topic="mco-codex", server="https://evil.invalid")
    assert posted[0][0] == f"https://ntfy.sh/{topic}"
    assert posted[0][1]["headers"]["Title"] == "BitCadence: alert"
    assert b"household" not in posted[0][1]["data"]


def test_vault_topic_is_used_when_plain_config_is_missing(monkeypatch):
    topic = "N4vK2xP7mQ9sT8wY5cF1hL6dB3zR0aGj"
    monkeypatch.setattr(ntfy_mod, "get_config", lambda: _Cfg({"NTFY_TOPIC_SECRET_ID": "ntfy/topic"}))
    monkeypatch.setattr(ntfy_mod, "_aws_vault_topic", lambda _config: topic)
    assert ntfy_mod.get_ntfy_config()["topic"] == topic
