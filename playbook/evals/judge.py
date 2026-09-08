"""Model-graded rationale. Offline it is a transparent heuristic; live it asks the API."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from playbook.agent.loop import RunTrace


class Judge(Protocol):
    name: str

    def score(self, trace: RunTrace, question: str) -> tuple[float, str]: ...


class OfflineJudge:
    """Rule-based stand-in: rewards a completed run, error-free tools and a summary that names
    the ticket. It exists so offline reports have the same shape as live ones."""

    name = "offline-heuristic"

    def score(self, trace: RunTrace, question: str) -> tuple[float, str]:
        notes: list[str] = []
        score = 0.0
        if trace.status == "completed":
            score += 0.4
            notes.append("run completed within the step budget")
        else:
            notes.append(f"run ended with status {trace.status}")
        errors = [c for c in trace.tool_calls if c.error]
        if trace.tool_calls and not errors:
            score += 0.3
            notes.append("no tool errors")
        elif errors:
            notes.append(f"{len(errors)} tool call(s) failed")
        keys = [c.result.get("issue_key") for c in trace.calls("jira.create_issue") if c.result]
        if keys and keys[0] in trace.final_text:
            score += 0.3
            notes.append(f"final summary names {keys[0]}")
        else:
            notes.append("final summary does not name the ticket")
        return round(score, 3), "; ".join(notes)


class LiveJudge:
    name = "model"

    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    def score(self, trace: RunTrace, question: str) -> tuple[float, str]:
        calls = "\n".join(f"- {c.name} {json.dumps(c.args)} -> {json.dumps(c.result)}" for c in trace.tool_calls)
        prompt = (
            "You are grading an operations agent's run against an expert's question.\n"
            f"Question: {question}\n\nIntake:\n{trace.user_message}\n\nTool calls:\n{calls}\n\n"
            f"Final message: {trace.final_text}\n\n"
            'Reply with JSON only: {"score": <0 to 1>, "rationale": "<one or two sentences>"}'
        )
        response = self.client.messages.create(
            model=self.model, max_tokens=300, messages=[{"role": "user", "content": prompt}]
        )
        text = "".join(getattr(b, "text", "") for b in response.content)
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return 0.0, f"unparseable judge reply: {text[:120]}"
        data = json.loads(m.group(0))
        return max(0.0, min(1.0, float(data.get("score", 0)))), str(data.get("rationale", ""))
