"""Tool schemas exposed to the model and the executors that call Jira, Slack and the KB."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from playbook.config import Settings

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "kb_search",
        "description": "Search the internal knowledge base for known issues matching a query.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "jira_create_issue",
        "description": "Create a Jira issue. Returns the new issue key.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "summary": {"type": "string"},
                "description": {"type": "string"},
                "issue_type": {"type": "string", "enum": ["Bug", "Task", "Incident"]},
                "priority": {
                    "type": "string",
                    "enum": ["Highest", "High", "Medium", "Low", "Lowest"],
                },
            },
            "required": ["project", "summary", "priority"],
        },
    },
    {
        "name": "jira_transition",
        "description": "Move a Jira issue to a new status by name.",
        "input_schema": {
            "type": "object",
            "properties": {"issue_key": {"type": "string"}, "status": {"type": "string"}},
            "required": ["issue_key", "status"],
        },
    },
    {
        "name": "jira_comment",
        "description": "Add a comment to a Jira issue.",
        "input_schema": {
            "type": "object",
            "properties": {"issue_key": {"type": "string"}, "body": {"type": "string"}},
            "required": ["issue_key", "body"],
        },
    },
    {
        "name": "slack_post",
        "description": "Post a message to a Slack channel (for example #support-escalations).",
        "input_schema": {
            "type": "object",
            "properties": {"channel": {"type": "string"}, "text": {"type": "string"}},
            "required": ["channel", "text"],
        },
    },
    {
        "name": "slack_lookup_channel",
        "description": "Find the Slack channel that owns a service or topic.",
        "input_schema": {
            "type": "object",
            "properties": {"service": {"type": "string"}},
            "required": ["service"],
        },
    },
]

# Dotted names used in SOPs and rubrics map to the API-safe tool names above.
DOTTED_TO_API = {
    "kb.search": "kb_search",
    "jira.create_issue": "jira_create_issue",
    "jira.transition": "jira_transition",
    "jira.comment": "jira_comment",
    "slack.post": "slack_post",
    "slack.lookup_channel": "slack_lookup_channel",
}
API_TO_DOTTED = {v: k for k, v in DOTTED_TO_API.items()}


class KnowledgeBase:
    """Keyword search over a small JSON article set; the same implementation in both modes."""

    def __init__(self, articles: list[dict[str, Any]]):
        self.articles = articles

    @classmethod
    def from_file(cls, path: Path | None) -> KnowledgeBase:
        if path is None or not path.exists():
            return cls([])
        return cls(json.loads(path.read_text()))

    def search(self, query: str) -> list[dict[str, Any]]:
        words = set(re.findall(r"[a-z0-9-]+", query.lower()))
        hits = []
        for art in self.articles:
            score = sum(1 for k in art["keywords"] if k in words)
            if score >= 2:
                hits.append({**art, "score": score})
        hits.sort(key=lambda a: -a["score"])
        return hits


class ToolExecutor:
    """Executes tool calls against Jira, Slack and the KB. Everything it does is returned as
    JSON-serialisable dicts so the trace is complete."""

    def __init__(self, settings: Settings, kb: KnowledgeBase, client: httpx.Client | None = None):
        self.settings = settings
        self.kb = kb
        self.http = client or httpx.Client(timeout=15.0)

    def _jira(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.settings.jira_token}"}
        r = self.http.request(method, self.settings.jira_base_url + path, json=body, headers=headers)
        r.raise_for_status()
        return r.json() if r.content else {}

    def _slack(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.settings.slack_token}"}
        r = self.http.request(
            method, self.settings.slack_base_url + path, json=body, headers=headers
        )
        r.raise_for_status()
        data = r.json()
        if data.get("ok") is False:
            raise RuntimeError(f"slack error: {data.get('error')}")
        return data

    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "kb_search":
            return {"matches": self.kb.search(args.get("query", ""))}
        if name == "jira_create_issue":
            fields = {
                "project": {"key": args["project"]},
                "summary": args["summary"],
                "description": args.get("description", ""),
                "issuetype": {"name": args.get("issue_type", "Task")},
                "priority": {"name": args["priority"]},
            }
            data = self._jira("POST", "/rest/api/3/issue", {"fields": fields})
            return {"issue_key": data["key"], "id": data.get("id")}
        if name == "jira_transition":
            key = args["issue_key"]
            self._jira(
                "POST",
                f"/rest/api/3/issue/{key}/transitions",
                {"transition": {"name": args["status"]}},
            )
            return {"issue_key": key, "status": args["status"]}
        if name == "jira_comment":
            key = args["issue_key"]
            data = self._jira("POST", f"/rest/api/3/issue/{key}/comment", {"body": args["body"]})
            return {"issue_key": key, "comment_id": data.get("id")}
        if name == "slack_post":
            data = self._slack(
                "POST", "/api/chat.postMessage", {"channel": args["channel"], "text": args["text"]}
            )
            return {"channel": args["channel"], "ts": data.get("ts")}
        if name == "slack_lookup_channel":
            data = self._slack("GET", "/api/conversations.list")
            wanted = args.get("service", "").lower()
            for ch in data.get("channels", []):
                topic = (ch.get("topic") or {}).get("value", "").lower()
                if wanted and (wanted in ch["name"].lower() or wanted in topic):
                    return {"channel": "#" + ch["name"], "found": True}
            return {"channel": None, "found": False}
        raise ValueError(f"unknown tool {name}")
