"""A Slack Web API stand-in: chat.postMessage and conversations.list, plus an inbox."""

from __future__ import annotations

import threading
from typing import Any

from fakes._http import FakeServer

DEFAULT_CHANNELS = [
    {"name": "support-escalations", "topic": "Escalated support cases"},
    {"name": "oncall-sev1", "topic": "Pages the sev1 on-call engineer"},
    {"name": "incidents", "topic": "Incident announcements"},
    {"name": "status-updates", "topic": "Customer-facing status"},
    {"name": "ic-oncall", "topic": "Incident commander pages"},
    {"name": "team-payments", "topic": "Owns payments-api and billing"},
    {"name": "team-identity", "topic": "Owns auth-service and sso"},
    {"name": "team-data", "topic": "Owns export-service and analytics"},
    {"name": "general", "topic": "Company wide"},
]


class SlackApp:
    def __init__(self, channels: list[dict[str, str]] | None = None) -> None:
        self.lock = threading.Lock()
        self.channels = [
            {"id": f"C{i:04d}", "name": c["name"], "topic": {"value": c["topic"]}}
            for i, c in enumerate(channels or DEFAULT_CHANNELS, start=1)
        ]
        self.messages: list[dict[str, Any]] = []

    def reset(self) -> None:
        with self.lock:
            self.messages.clear()

    def handle(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        if path == "/health":
            return 200, {"ok": True, "service": "fake-slack"}
        if path == "/_inbox":
            if method == "DELETE":
                self.reset()
                return 200, {"ok": True}
            return 200, {"messages": self.messages}
        if path == "/api/conversations.list":
            return 200, {"ok": True, "channels": self.channels}
        if method == "POST" and path == "/api/chat.postMessage":
            channel = str(body.get("channel", "")).lstrip("#")
            text = body.get("text")
            if not channel or not text:
                return 200, {"ok": False, "error": "invalid_arguments"}
            if channel not in {c["name"] for c in self.channels}:
                return 200, {"ok": False, "error": "channel_not_found"}
            with self.lock:
                ts = f"{1700000000 + len(self.messages)}.000100"
                self.messages.append({"channel": "#" + channel, "text": text, "ts": ts})
            return 200, {"ok": True, "channel": channel, "ts": ts}
        raise KeyError(path)


def serve(port: int) -> FakeServer:
    return FakeServer(SlackApp(), port).start()
