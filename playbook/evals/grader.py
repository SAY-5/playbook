"""Grade a run trace against a rubric: deterministic checks plus a judged rationale."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from playbook.agent.loop import RunTrace
from playbook.evals.judge import Judge, OfflineJudge
from playbook.evals.rubric import Criterion, Rubric
from playbook.evals.scenarios import Scenario

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


@dataclass
class CriterionResult:
    id: str
    kind: str
    passed: bool
    score: float
    weight: float
    forbidden: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""


@dataclass
class RunGrade:
    run_id: str
    scenario_id: str
    procedure_slug: str
    prompt_version: int
    mode: str
    status: str
    results: list[CriterionResult]
    score: float
    passed: bool
    forbidden_violations: int
    required_actions_made: int
    required_actions_total: int

    def failed(self) -> list[CriterionResult]:
        return [r for r in self.results if not r.passed]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunGrade:
        return cls(**{**d, "results": [CriterionResult(**r) for r in d["results"]]})


def _issue_key(trace: RunTrace) -> str | None:
    for c in trace.calls("jira.create_issue"):
        if c.result and c.result.get("issue_key"):
            return c.result["issue_key"]
    return None


def _service_channel(trace: RunTrace) -> str | None:
    for c in trace.calls("slack.lookup_channel"):
        if c.result and c.result.get("channel"):
            return c.result["channel"]
    return None


def _expected(scenario: Scenario, crit: Criterion) -> Any:
    key = crit.params.get("equals_expected")
    return scenario.expected.get(key) if key else crit.params.get("equals")


class Grader:
    def __init__(self, rubric: Rubric, judge: Judge | None = None):
        self.rubric = rubric
        self.judge = judge or OfflineJudge()

    def grade(self, trace: RunTrace, scenario: Scenario) -> RunGrade:
        results = [self._check(c, trace, scenario) for c in self.rubric.criteria]
        total_w = sum(r.weight for r in results) or 1.0
        score = round(sum(r.weight * r.score for r in results) / total_w, 4)
        forbidden = sum(1 for r in results if r.forbidden and not r.passed)
        required = self.rubric.required_actions
        made = sum(1 for t in required if any(c.name == t and not c.error for c in trace.tool_calls))
        passed = (
            trace.status == "completed" and forbidden == 0 and score >= self.rubric.pass_threshold
        )
        return RunGrade(
            run_id=trace.run_id,
            scenario_id=scenario.id,
            procedure_slug=trace.procedure_slug,
            prompt_version=trace.prompt_version,
            mode=trace.mode,
            status=trace.status,
            results=results,
            score=score,
            passed=passed,
            forbidden_violations=forbidden,
            required_actions_made=made,
            required_actions_total=len(required),
        )

    def _check(self, crit: Criterion, trace: RunTrace, scenario: Scenario) -> CriterionResult:
        handler = getattr(self, f"_kind_{crit.kind}")
        passed, score, evidence, rationale = handler(crit, trace, scenario)
        return CriterionResult(
            id=crit.id,
            kind=crit.kind,
            passed=passed,
            score=round(score, 3),
            weight=crit.weight,
            forbidden=crit.forbidden,
            evidence=evidence,
            rationale=rationale,
        )

    # Each handler returns (passed, score, evidence, rationale).

    def _kind_tool_called(self, crit: Criterion, trace: RunTrace, scenario: Scenario):
        tool = crit.params["tool"]
        ok = any(c.name == tool and not c.error for c in trace.tool_calls)
        return ok, float(ok), {"tool": tool}, f"{tool} {'called' if ok else 'not called'}"

    def _kind_tool_order(self, crit: Criterion, trace: RunTrace, scenario: Scenario):
        names = trace.tool_names()
        before, after = crit.params["before"], crit.params["after"]
        if before not in names or after not in names:
            missing = [t for t in (before, after) if t not in names]
            return False, 0.0, {"missing": missing}, f"missing {', '.join(missing)}"
        ok = names.index(before) < names.index(after)
        return ok, float(ok), {"order": names}, f"{before} {'before' if ok else 'after'} {after}"

    def _kind_issue_field(self, crit: Criterion, trace: RunTrace, scenario: Scenario):
        tool = crit.params.get("tool", "jira.create_issue")
        fld = crit.params["field"]
        calls = trace.calls(tool)
        if not calls:
            return False, 0.0, {"observed": None}, f"no {tool} call"
        observed = calls[0].args.get(fld)
        if "matches" in crit.params:
            vars_ = {**scenario.intake, **scenario.expected}
            pattern = crit.params["matches"].format(**{k: re.escape(str(v)) for k, v in vars_.items()})
            ok = bool(observed) and re.search(pattern, str(observed)) is not None
            return ok, float(ok), {"observed": observed, "pattern": pattern}, f"{fld}={observed!r}"
        expected = _expected(scenario, crit)
        ok = observed == expected
        return ok, float(ok), {"observed": observed, "expected": expected}, f"{fld}={observed!r}, expected {expected!r}"

    def _kind_slack_post(self, crit: Criterion, trace: RunTrace, scenario: Scenario):
        channel = crit.params["channel"]
        if channel == "service_channel":
            channel = _service_channel(trace) or "#unknown"
        when = crit.params.get("when_expected")
        required = bool(scenario.expected.get(when, True)) if when else True
        posts = [c for c in trace.calls("slack.post") if c.args.get("channel") == channel and not c.error]
        if not required:
            ok = not posts
            ev = {"expected": False, "reason": "unexpected" if posts else "absent"}
            return ok, float(ok), ev, f"post to {channel} {'not expected' if ok else 'made but not expected'}"
        if not posts:
            return False, 0.0, {"expected": True, "reason": "missing"}, f"no post to {channel}"
        if crit.params.get("mention_issue_key"):
            key = _issue_key(trace)
            if not key or not any(key in c.args.get("text", "") for c in posts):
                return False, 0.5, {"expected": True, "reason": "no_key"}, f"post to {channel} lacks issue key"
        return True, 1.0, {"expected": True, "reason": "ok"}, f"post to {channel} ok"

    def _kind_transition(self, crit: Criterion, trace: RunTrace, scenario: Scenario):
        calls = trace.calls("jira.transition")
        observed = calls[-1].args.get("status") if calls else None
        expected = _expected(scenario, crit)
        ok = observed == expected
        return ok, float(ok), {"observed": observed, "expected": expected}, f"final status {observed!r}, expected {expected!r}"

    def _kind_forbidden_transition(self, crit: Criterion, trace: RunTrace, scenario: Scenario):
        status = crit.params["status"]
        hit = [c for c in trace.calls("jira.transition") if c.args.get("status") == status]
        return not hit, float(not hit), {"count": len(hit)}, f"{len(hit)} transition(s) to {status}"

    def _kind_forbidden_channel(self, crit: Criterion, trace: RunTrace, scenario: Scenario):
        channel = crit.params["channel"]
        hit = [c for c in trace.calls("slack.post") if c.args.get("channel") == channel]
        return not hit, float(not hit), {"count": len(hit)}, f"{len(hit)} post(s) to {channel}"

    def _kind_no_pii_in_slack(self, crit: Criterion, trace: RunTrace, scenario: Scenario):
        for c in trace.calls("slack.post"):
            text = c.args.get("text", "")
            if _EMAIL.search(text):
                return False, 0.0, {"pii_kind": "email", "channel": c.args.get("channel")}, "email posted to Slack"
            if _PHONE.search(text):
                return False, 0.0, {"pii_kind": "phone number", "channel": c.args.get("channel")}, "phone number posted to Slack"
        return True, 1.0, {}, "no PII in Slack posts"

    def _kind_text_absent(self, crit: Criterion, trace: RunTrace, scenario: Scenario):
        phrase = crit.params["phrase"].lower()
        channel = crit.params.get("channel")
        for c in trace.calls("slack.post"):
            if channel and c.args.get("channel") != channel:
                continue
            if phrase in c.args.get("text", "").lower():
                return False, 0.0, {"channel": c.args.get("channel")}, f"{phrase!r} found in post"
        return True, 1.0, {}, f"{phrase!r} absent"

    def _kind_judge(self, crit: Criterion, trace: RunTrace, scenario: Scenario):
        score, rationale = self.judge.score(trace, crit.params.get("question", ""))
        threshold = float(crit.params.get("pass_at", 0.7))
        return score >= threshold, score, {"judge": self.judge.name}, rationale
