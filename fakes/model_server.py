"""A deterministic stand-in for the Anthropic Messages API used in offline mode.

It speaks the request and response shape of `POST /v1/messages`, including `tool_use` blocks
and `tool_result` turns, so the real `anthropic` SDK talks to it unchanged.

Behaviour comes from a small rule engine that reads the system prompt. It executes the SOP steps
in order and only honours instructions written as explicit conditional directives, for example
`When severity is sev1, post to #oncall-sev1 mentioning the issue key.` Prose it cannot parse is
ignored, which is what makes the feedback loop observable: a correction appended to a step changes
what the next run does. The grammar is documented in ARCHITECTURE.md.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from fakes._http import FakeServer

_STEP_HEADER = re.compile(r"^### Step (\d+): (?P<title>.*?) \[(?P<id>[\w-]+)\](?: \(tool: (?P<tool>[\w.]+)\))?")
_COND_ACTION = re.compile(r"^(?:if|when)\s+(?P<cond>.+?),\s*(?P<action>.+)$", re.I)
_OTHERWISE = re.compile(r"^otherwise\s+(?P<action>.+)$", re.I)
_SEV = re.compile(r"\bsev[1-4]\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_IMPACTS = ("full outage", "partial outage", "degraded", "internal")
_TIERS = ("enterprise", "pro", "free")


@dataclass
class Cond:
    severity: str | None = None
    severity_unknown: bool = False
    tier: str | None = None
    kb_hit: bool | None = None
    customer_facing: bool | None = None
    impact: str | None = None
    report_phrase: str | None = None
    slack_context: bool = False

    @property
    def specificity(self) -> int:
        return sum(
            1
            for v in (
                self.severity,
                self.tier,
                self.kb_hit,
                self.customer_facing,
                self.impact,
                self.report_phrase,
            )
            if v is not None
        ) + int(self.severity_unknown)

    def holds(self, facts: dict[str, Any]) -> bool:
        if self.severity and facts.get("severity") != self.severity:
            return False
        if self.severity_unknown and facts.get("severity_stated"):
            return False
        if self.tier and facts.get("tier") != self.tier:
            return False
        if self.kb_hit is not None and bool(facts.get("kb_hit")) != self.kb_hit:
            return False
        if self.customer_facing is not None and bool(facts.get("customer_facing")) != self.customer_facing:
            return False
        if self.impact and facts.get("impact") != self.impact:
            return False
        if self.report_phrase and self.report_phrase not in facts.get("report", "").lower():
            return False
        return True


def parse_cond(text: str) -> Cond | None:
    """Return a Cond when every clause is understood, otherwise None."""
    cond = Cond()
    for clause in re.split(r"\s+and\s+", text.strip().lower()):
        clause = clause.strip().rstrip(".")
        m = _SEV.search(clause)
        if m and "not stated" not in clause and "unknown" not in clause:
            cond.severity = m.group(0).lower()
            continue
        if "severity" in clause and ("not stated" in clause or "unknown" in clause):
            cond.severity_unknown = True
            continue
        tier = next((t for t in _TIERS if t in clause), None)
        if tier and ("tier" in clause or "account" in clause):
            cond.tier = tier
            continue
        if "kb" in clause or "knowledge base" in clause:
            cond.kb_hit = not ("no " in clause or "nothing" in clause or "not " in clause)
            continue
        if "customer-facing" in clause or "customer facing" in clause:
            cond.customer_facing = not clause.startswith("not ") and " not " not in clause
            continue
        impact = next((i for i in _IMPACTS if i in clause), None)
        if impact and "impact" in clause:
            cond.impact = impact
            continue
        pm = re.search(r'report mentions "([^"]+)"', clause)
        if pm:
            cond.report_phrase = pm.group(1).lower()
            continue
        if "posting to slack" in clause:
            cond.slack_context = True
            continue
        return None
    return cond


@dataclass
class Directive:
    kind: str
    cond: Cond | None
    step_id: str | None
    field: str = ""
    value: str = ""
    channel: str = ""
    mention_key: bool = False
    else_value: str = ""


def parse_action(text: str, cond: Cond | None, step_id: str | None) -> Directive | None:
    t = text.strip().rstrip(".")
    low = t.lower()
    m = re.match(r"^use project (\w+)", t, re.I)
    if m:
        return Directive("project", cond, step_id, value=m.group(1).upper())
    m = re.match(r'^set (\w+) to "([^"]+)"', t, re.I)
    if m:
        return Directive("set", cond, step_id, field=m.group(1).lower(), value=m.group(2))
    m = re.match(r"^treat severity as (sev[1-4])", t, re.I)
    if m:
        return Directive("set", cond, step_id, field="severity", value=m.group(1).lower())
    m = re.match(r"^post to (#[\w-]+|the service channel)( mentioning the issue key)?", t, re.I)
    if m:
        return Directive("post", cond, step_id, channel=m.group(1).lower(), mention_key=bool(m.group(2)))
    m = re.match(r'^transition to "([^"]+)"', t, re.I)
    if m:
        return Directive("transition", cond, step_id, value=m.group(1))
    m = re.match(r"^do not include the customer (email|phone number)", low)
    if m:
        return Directive("exclude", cond, step_id, value=m.group(1))
    return None


@dataclass
class ParsedPrompt:
    steps: list[tuple[str, str | None]] = field(default_factory=list)  # (id, tool)
    directives: list[Directive] = field(default_factory=list)


def parse_prompt(system: str) -> ParsedPrompt:
    parsed = ParsedPrompt()
    step_id: str | None = None
    for raw in system.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _STEP_HEADER.match(line)
        if m:
            step_id = m.group("id")
            parsed.steps.append((step_id, m.group("tool")))
            continue
        if line.startswith("## "):
            step_id = None
            continue
        if line.startswith("- "):
            line = line[2:]
        line = re.sub(r"^\(v\d+\)\s*", "", line)
        for sentence in re.split(r"(?<=[.!])\s+(?=[A-Z])", line):
            sentence = sentence.strip()
            cm = _COND_ACTION.match(sentence)
            om = _OTHERWISE.match(sentence)
            if cm:
                cond = parse_cond(cm.group("cond"))
                if cond is None:
                    continue
                d = parse_action(cm.group("action"), cond, step_id)
            elif om:
                d = parse_action(om.group("action"), None, step_id)
                if d and d.kind == "transition":
                    for prev in reversed(parsed.directives):
                        if prev.kind == "transition" and prev.cond is not None:
                            prev.else_value = d.value
                            break
                    d = None
            else:
                d = parse_action(sentence, None, step_id)
            if d is not None:
                parsed.directives.append(d)
    return parsed


def parse_intake(text: str) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z][\w -]*):\s*(.*)$", line.strip())
        if m:
            facts[m.group(1).strip().lower().replace(" ", "_")] = m.group(2).strip()
    sev = facts.get("severity", "").lower()
    facts["severity_stated"] = bool(_SEV.fullmatch(sev))
    facts["severity"] = sev if facts["severity_stated"] else None
    facts["tier"] = facts.get("tier", "").lower() or None
    facts["impact"] = facts.get("impact", "").lower() or None
    facts["customer_facing"] = facts.get("customer-facing", facts.get("customer_facing", "")).lower() in ("yes", "true")
    return facts


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class RuleEngine:
    """Builds a plan of tool calls for one conversation and serves it turn by turn."""

    def __init__(self, model: str = "fake-model"):
        self.model = model

    def _pick(self, directives: list[Directive], field_name: str, facts: dict[str, Any]) -> str | None:
        best: Directive | None = None
        for d in directives:
            if d.kind != "set" or d.field != field_name:
                continue
            if d.cond is not None and not d.cond.holds(facts):
                continue
            spec = d.cond.specificity if d.cond else 0
            if best is None or spec >= (best.cond.specificity if best.cond else 0):
                best = d
        return best.value if best else None

    def _facts(self, parsed: ParsedPrompt, intake: str, state: dict[str, Any]) -> dict[str, Any]:
        facts = parse_intake(intake)
        facts.update(state)
        if facts.get("severity") is None:
            inferred = self._pick(parsed.directives, "severity", facts)
            facts["severity"] = inferred or "sev3"
        return facts

    def plan(self, parsed: ParsedPrompt, intake: str, state: dict[str, Any]) -> list[dict[str, Any]]:
        facts = self._facts(parsed, intake, state)
        ds = parsed.directives
        project = next((d.value for d in ds if d.kind == "project"), "OPS")
        excluded = {d.value for d in ds if d.kind == "exclude" and (d.cond is None or d.cond.holds(facts))}
        title = facts.get("title", "untitled")
        key = state.get("issue_key", "")
        contact = facts.get("contact", "")
        is_incident = "service" in facts
        fmt = _SafeDict(
            severity=facts.get("severity") or "",
            title=title,
            impact=facts.get("impact") or "",
            service=facts.get("service") or "",
            account=facts.get("account") or "",
        )

        def post_text(mention: bool) -> str:
            parts = []
            if mention and key:
                parts.append(f"{key}:")
            parts.append(f"[{facts.get('impact') or facts.get('severity')}] {title}")
            if facts.get("account"):
                parts.append(f"(account {facts['account']})")
            if is_incident:
                parts.append("Status: investigating.")
            if contact:
                kind = "email" if _EMAIL.search(contact) else "phone number" if _PHONE.search(contact) else None
                if kind and kind not in excluded:
                    parts.append(f"Contact: {contact}")
            return " ".join(parts)

        first_post_step = next((sid for sid, tool in parsed.steps if tool == "slack.post"), None)
        transition_step = next((sid for sid, tool in parsed.steps if tool == "jira.transition"), None)
        calls: list[dict[str, Any]] = []
        for sid, tool in parsed.steps:
            if tool == "kb.search":
                calls.append({"name": "kb_search", "input": {"query": title}})
            elif tool == "slack.lookup_channel":
                calls.append({"name": "slack_lookup_channel", "input": {"service": facts.get("service", "")}})
            elif tool == "jira.create_issue":
                summary_t = self._pick(ds, "summary", facts) or "{title}"
                calls.append(
                    {
                        "name": "jira_create_issue",
                        "input": {
                            "project": project,
                            "summary": summary_t.format_map(fmt),
                            "description": f"Account {facts.get('account', 'n/a')}. {facts.get('report', '')}".strip(),
                            "issue_type": "Incident" if is_incident else "Bug",
                            "priority": self._pick(ds, "priority", facts) or "Medium",
                        },
                    }
                )
            elif tool == "jira.comment":
                matches = state.get("kb_matches") or []
                kb = "; ".join(f"{m['id']} {m['title']}" for m in matches) or "no KB matches"
                channels = state.get("posted", [])
                body = f"KB: {kb}. Account {facts.get('account', 'n/a')} ({facts.get('tier') or 'n/a'})."
                if is_incident:
                    body = f"Notified: {', '.join(channels) or 'none'}. Impact: {facts.get('impact')}."
                calls.append({"name": "jira_comment", "input": {"issue_key": key, "body": body}})
            elif tool == "slack.post":
                posts: dict[str, bool] = {}
                for d in ds:
                    if d.kind != "post":
                        continue
                    owner = d.step_id or first_post_step
                    if owner != sid or (d.cond is not None and not d.cond.holds(facts)):
                        continue
                    ch = state.get("service_channel") or "" if d.channel == "the service channel" else d.channel
                    if not ch:
                        continue
                    posts[ch] = posts.get(ch, False) or d.mention_key
                for ch, mention in posts.items():
                    calls.append({"name": "slack_post", "input": {"channel": ch, "text": post_text(mention)}})
            elif tool == "jira.transition":
                status = None
                for d in ds:
                    if d.kind != "transition" or (d.step_id or transition_step) != sid:
                        continue
                    if d.cond is None or d.cond.holds(facts):
                        status = d.value
                        break
                    if d.else_value:
                        status = d.else_value
                if status:
                    calls.append({"name": "jira_transition", "input": {"issue_key": key, "status": status}})
        return calls

    @staticmethod
    def _state_from(messages: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        names: dict[str, str] = {}
        inputs: dict[str, dict[str, Any]] = {}
        state: dict[str, Any] = {"posted": []}
        done = 0
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") == "tool_use":
                    names[block["id"]] = block["name"]
                    inputs[block["id"]] = block.get("input", {})
                    done += 1
                elif block.get("type") == "tool_result":
                    name = names.get(block["tool_use_id"])
                    raw = block.get("content")
                    text = raw if isinstance(raw, str) else "".join(b.get("text", "") for b in raw or [])
                    try:
                        data = json.loads(text) if text else {}
                    except json.JSONDecodeError:
                        data = {}
                    if name == "jira_create_issue" and data.get("issue_key"):
                        state["issue_key"] = data["issue_key"]
                    elif name == "kb_search":
                        state["kb_matches"] = data.get("matches", [])
                        state["kb_hit"] = bool(data.get("matches"))
                    elif name == "slack_lookup_channel":
                        state["service_channel"] = data.get("channel") or ""
                    elif name == "slack_post":
                        state["posted"].append(inputs.get(block["tool_use_id"], {}).get("channel", ""))
        return done, state

    def respond(self, request: dict[str, Any]) -> dict[str, Any]:
        system = request.get("system") or ""
        if isinstance(system, list):
            system = "".join(b.get("text", "") for b in system)
        messages = request.get("messages") or []
        if not messages:
            raise ValueError("messages required")
        first = messages[0].get("content")
        intake = first if isinstance(first, str) else "".join(b.get("text", "") for b in first)
        parsed = parse_prompt(system)
        done, state = self._state_from(messages)
        calls = self.plan(parsed, intake, state)
        model = request.get("model", self.model)
        in_tokens = (len(system) + sum(len(json.dumps(m)) for m in messages)) // 4

        if done < len(calls):
            call = calls[done]
            content = [
                {"type": "text", "text": f"Step {done + 1}: calling {call['name']}."},
                {"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:16]}", **call},
            ]
            stop = "tool_use"
        else:
            key = state.get("issue_key") or "no ticket"
            content = [{"type": "text", "text": f"Procedure complete. Ticket {key}; {done} tool calls."}]
            stop = "end_turn"
        return {
            "id": f"msg_{uuid.uuid4().hex[:20]}",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": in_tokens, "output_tokens": len(json.dumps(content)) // 4},
        }


class ModelApp:
    def __init__(self) -> None:
        self.engine = RuleEngine()
        self.requests = 0

    def handle(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        if path == "/health":
            return 200, {"ok": True, "service": "fake-model", "requests": self.requests}
        if method == "POST" and path == "/v1/messages":
            self.requests += 1
            return 200, self.engine.respond(body)
        raise KeyError(path)


def serve(port: int, host: str = "127.0.0.1") -> FakeServer:
    return FakeServer(ModelApp(), port, host).start()
