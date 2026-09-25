"""A Jira Cloud REST stand-in: issues, transitions, comments, plus an inbox for evidence."""

from __future__ import annotations

import re
import threading
from typing import Any

from fakes._http import FakeServer

_ISSUE = re.compile(r"^/rest/api/3/issue/(?P<key>[A-Z]+-\d+)(?P<rest>/transitions|/comment)?$")


class JiraApp:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.issues: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.counters: dict[str, int] = {}

    def reset(self) -> None:
        with self.lock:
            self.issues.clear()
            self.events.clear()
            self.counters.clear()

    def handle(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        if path == "/health":
            return 200, {"ok": True, "service": "fake-jira"}
        if path == "/_inbox":
            if method == "DELETE":
                self.reset()
                return 200, {"ok": True}
            return 200, {"issues": self.issues, "events": self.events}
        if method == "POST" and path == "/rest/api/3/issue":
            return 201, self._create(body)
        m = _ISSUE.match(path)
        if not m:
            raise KeyError(path)
        key = m.group("key")
        with self.lock:
            if key not in self.issues:
                raise KeyError(key)
        if method == "GET" and not m.group("rest"):
            return 200, self.issues[key]
        if method == "POST" and m.group("rest") == "/transitions":
            status = (body.get("transition") or {}).get("name")
            if not status:
                raise ValueError("transition.name required")
            with self.lock:
                self.issues[key]["fields"]["status"] = {"name": status}
                self.events.append({"type": "transition", "key": key, "status": status})
            return 204, {}
        if method == "POST" and m.group("rest") == "/comment":
            text = body.get("body")
            if not text:
                raise ValueError("body required")
            with self.lock:
                comments = self.issues[key].setdefault("comments", [])
                comments.append({"id": str(len(comments) + 1), "body": text})
                self.events.append({"type": "comment", "key": key, "body": text})
            return 201, {"id": str(len(comments))}
        raise KeyError(path)

    def _create(self, body: dict[str, Any]) -> dict[str, Any]:
        fields = body.get("fields") or {}
        project = (fields.get("project") or {}).get("key")
        if not project or not fields.get("summary"):
            raise ValueError("fields.project.key and fields.summary are required")
        with self.lock:
            n = self.counters.get(project, 100) + 1
            self.counters[project] = n
            key = f"{project}-{n}"
            issue = {
                "id": str(10000 + len(self.issues)),
                "key": key,
                "fields": {
                    "project": {"key": project},
                    "summary": fields["summary"],
                    "description": fields.get("description", ""),
                    "issuetype": fields.get("issuetype", {"name": "Task"}),
                    "priority": fields.get("priority", {"name": "Medium"}),
                    "status": {"name": "Open"},
                },
                "comments": [],
            }
            self.issues[key] = issue
            self.events.append({"type": "create", "key": key, "fields": issue["fields"]})
        return {"id": issue["id"], "key": key}


def serve(port: int, host: str = "127.0.0.1") -> FakeServer:
    return FakeServer(JiraApp(), port, host).start()
