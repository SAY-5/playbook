from pathlib import Path

from playbook.agent.loop import RunTrace, ToolCall
from playbook.evals.grader import Grader
from playbook.evals.rubric import Rubric
from playbook.evals.scenarios import ScenarioSet


def _trace(calls: list[tuple[str, dict, dict | None]], status: str = "completed") -> RunTrace:
    trace = RunTrace(
        run_id="r1", procedure_slug="support-triage", prompt_version=1, scenario_id="triage-01",
        mode="offline", model="fake", system_prompt="", user_message="", started_at="", status=status,
        final_text="Procedure complete. Ticket SUP-101.",
    )
    for i, (name, args, result) in enumerate(calls, start=1):
        trace.tool_calls.append(ToolCall(i, f"toolu_{i}", name, args, result, None, 1))
    return trace


GOOD = [
    ("kb.search", {"query": "SSO"}, {"matches": [{"id": "KB-101"}]}),
    ("jira.create_issue", {"project": "SUP", "summary": "[sev1] SSO login returns 500 after certificate rotation", "priority": "Highest"}, {"issue_key": "SUP-101"}),
    ("jira.comment", {"issue_key": "SUP-101", "body": "KB-101"}, {"issue_key": "SUP-101"}),
    ("slack.post", {"channel": "#support-escalations", "text": "SUP-101: [sev1] SSO (account ACC-1042)"}, {"ts": "1"}),
    ("slack.post", {"channel": "#oncall-sev1", "text": "SUP-101: [sev1] SSO"}, {"ts": "2"}),
    ("jira.transition", {"issue_key": "SUP-101", "status": "Waiting for Customer"}, {"status": "Waiting for Customer"}),
]


def _grade(triage_dir: Path, calls, status="completed"):
    rubric = Rubric.load(triage_dir / "rubric.yaml")
    scenario = ScenarioSet.load(triage_dir / "scenarios.yaml").get("triage-01")
    return Grader(rubric).grade(_trace(calls, status), scenario)


def _result(grade, cid):
    return next(r for r in grade.results if r.id == cid)


def test_expert_run_passes_every_criterion(triage_dir: Path):
    grade = _grade(triage_dir, GOOD)
    assert grade.passed and grade.score == 1.0
    assert grade.forbidden_violations == 0
    assert (grade.required_actions_made, grade.required_actions_total) == (2, 2)
    assert _result(grade, "run_quality").rationale.endswith("final summary names SUP-101")


def test_missing_and_misordered_required_actions(triage_dir: Path):
    reordered = [GOOD[1], GOOD[0], *GOOD[2:]]
    grade = _grade(triage_dir, reordered)
    assert not _result(grade, "kb_before_ticket").passed
    without_kb = GOOD[1:]
    grade = _grade(triage_dir, without_kb)
    assert not _result(grade, "kb_searched").passed
    assert _result(grade, "kb_before_ticket").evidence == {"missing": ["kb.search"]}
    assert grade.required_actions_made == 1


def test_field_checks_and_slack_evidence(triage_dir: Path):
    wrong_priority = [*GOOD]
    wrong_priority[1] = ("jira.create_issue", {"project": "SUP", "summary": "SSO login", "priority": "Medium"}, {"issue_key": "SUP-101"})
    grade = _grade(triage_dir, wrong_priority)
    prio = _result(grade, "priority_matches_matrix")
    assert not prio.passed and prio.evidence == {"observed": "Medium", "expected": "Highest"}
    assert not _result(grade, "summary_prefixed").passed
    no_key = [*GOOD]
    no_key[3] = ("slack.post", {"channel": "#support-escalations", "text": "[sev1] SSO"}, {"ts": "1"})
    grade = _grade(triage_dir, no_key)
    esc = _result(grade, "escalated_when_required")
    assert (esc.passed, esc.score, esc.evidence["reason"]) == (False, 0.5, "no_key")
    missing = [c for c in GOOD if c[1].get("channel") != "#oncall-sev1"]
    grade = _grade(triage_dir, missing)
    assert _result(grade, "oncall_paged_for_sev1").evidence["reason"] == "missing"
    assert not grade.passed


def test_forbidden_actions_fail_the_run(triage_dir: Path):
    leak = [*GOOD]
    leak[3] = ("slack.post", {"channel": "#support-escalations", "text": "SUP-101 contact ops@example.com"}, {"ts": "1"})
    grade = _grade(triage_dir, leak)
    pii = _result(grade, "no_pii_in_slack")
    assert not pii.passed and pii.evidence["pii_kind"] == "email"
    assert grade.forbidden_violations == 1 and not grade.passed
    done = [*GOOD, ("jira.transition", {"issue_key": "SUP-101", "status": "Done"}, {})]
    grade = _grade(triage_dir, done)
    assert not _result(grade, "never_done").passed
    assert not _result(grade, "final_state").passed


def test_incomplete_run_never_passes(triage_dir: Path):
    grade = _grade(triage_dir, GOOD, status="max_steps")
    assert not grade.passed
    assert _result(grade, "run_quality").score < 0.7
