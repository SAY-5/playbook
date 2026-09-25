import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from playbook.agent.loop import RunTrace, ToolCall
from playbook.agent.prompt import PromptSpec
from playbook.agent.store import LocalRunStore
from playbook.cli import main
from playbook.config import Settings
from playbook.evals.grader import CriterionResult, RunGrade
from playbook.evals.report import VersionReport
from playbook.feedback.approval import PromotionLog
from playbook.feedback.review import KIND as PROPOSALS
from playbook.ops import collect_ops, format_ops, measure, write_run_artifact

TRIAGE = "support-triage"
INCIDENT = "incident-communications"


def _grade(slug: str, version: int, scenario_id: str, passed: bool, forbidden: tuple[str, ...] = ()) -> RunGrade:
    results = [
        CriterionResult(id="kb_searched", kind="tool_called", passed=True, score=1.0, weight=1.0, forbidden=False)
    ]
    results += [
        CriterionResult(id=c, kind="no_pii_in_slack", passed=False, score=0.0, weight=1.0, forbidden=True)
        for c in forbidden
    ]
    return RunGrade(
        run_id=f"{scenario_id}-v{version}",
        scenario_id=scenario_id,
        procedure_slug=slug,
        prompt_version=version,
        mode="offline",
        status="completed",
        results=results,
        score=1.0 if passed else 0.5,
        passed=passed,
        forbidden_violations=len(forbidden),
        required_actions_made=2,
        required_actions_total=2,
    )


def _report(slug: str, version: int, grades: list[RunGrade]) -> VersionReport:
    passed = sum(1 for g in grades if g.passed)
    return VersionReport(
        procedure_slug=slug,
        prompt_version=version,
        mode="offline",
        scenarios=len(grades),
        passed=passed,
        pass_rate=round(passed / len(grades), 4),
        mean_score=round(sum(g.score for g in grades) / len(grades), 4),
        per_criterion={"kb_searched": 1.0},
        required_action_coverage=1.0,
        forbidden_violations=sum(g.forbidden_violations for g in grades),
        grades=grades,
    )


def _trace(slug: str, version: int, scenario_id: str, calls: list[tuple[str, int]], at: str, ms: int) -> RunTrace:
    return RunTrace(
        run_id=f"{scenario_id}-v{version}",
        procedure_slug=slug,
        prompt_version=version,
        scenario_id=scenario_id,
        mode="offline",
        model="fake",
        system_prompt="s",
        user_message="u",
        started_at=at,
        finished_at=at,
        duration_ms=ms,
        tool_calls=[
            ToolCall(turn=1, tool_use_id=f"t{i}", name=name, args={}, result={}, error=None, duration_ms=d)
            for i, (name, d) in enumerate(calls)
        ],
        status="completed",
    )


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    """A runs directory with two procedures, three versions, five runs and nine tool calls."""
    runs = tmp_path / "runs"
    store = LocalRunStore(runs)

    for version in (1, 2):
        store.save_prompt(PromptSpec(procedure_slug=TRIAGE, version=version))
    store.save_report(
        _report(TRIAGE, 1, [_grade(TRIAGE, 1, "s-01", True), _grade(TRIAGE, 1, "s-02", False, ("no_pii_in_slack",))])
    )
    store.save_report(_report(TRIAGE, 2, [_grade(TRIAGE, 2, "s-01", True), _grade(TRIAGE, 2, "s-02", True)]))
    for trace in (
        _trace(TRIAGE, 1, "s-01", [("kb.search", 1), ("jira.create_issue", 3)], "2026-09-10T09:00:00+00:00", 10),
        _trace(TRIAGE, 1, "s-02", [("kb.search", 2)], "2026-09-10T09:00:01+00:00", 20),
        _trace(
            TRIAGE,
            2,
            "s-01",
            [("kb.search", 1), ("jira.create_issue", 5), ("slack.post", 9)],
            "2026-09-10T09:00:02+00:00",
            30,
        ),
        _trace(TRIAGE, 2, "s-02", [("slack.post", 4)], "2026-09-10T09:00:03+00:00", 40),
    ):
        store.save_run(trace)
    for pid, status in (("p1-01", "approved"), ("p1-02", "pending")):
        store.save_record(
            PROPOSALS,
            TRIAGE,
            pid,
            {
                "id": pid,
                "procedure_slug": TRIAGE,
                "source_version": 1,
                "step_id": "escalate",
                "text": "rule",
                "criterion": "no_pii_in_slack",
                "evidence": "failed in v1 on s-02",
                "status": status,
            },
        )
    PromotionLog(store, TRIAGE).decide(store.load_report(TRIAGE, 2), [], "dana")

    store.save_prompt(PromptSpec(procedure_slug=INCIDENT, version=1))
    store.save_report(
        _report(
            INCIDENT,
            1,
            [
                _grade(INCIDENT, 1, "i-01", True),
                _grade(INCIDENT, 1, "i-02", False, ("never_general", "not_resolved_in_first_post")),
            ],
        )
    )
    store.save_run(
        _trace(INCIDENT, 1, "i-01", [("slack.lookup_channel", 6), ("slack.post", 8)], "2026-09-10T09:00:04+00:00", 50)
    )
    return runs


def test_ops_summary_counts_on_the_seeded_fixture(seeded: Path):
    summary = collect_ops(LocalRunStore(seeded))
    assert summary.location == str(seeded)
    assert [p.slug for p in summary.procedures] == [INCIDENT, TRIAGE]
    assert summary.total_versions == 3
    assert summary.total_scenarios == 4
    assert summary.open_forbidden == 2
    assert summary.total_runs == 5
    assert summary.total_tool_calls == 9

    triage = summary.procedures[1]
    assert triage.versions == [1, 2] and triage.latest_version == 2
    assert triage.promoted_version == 2
    assert triage.pass_rates == [(1, 0.5), (2, 1.0)]
    assert triage.open_forbidden == 0 and triage.open_forbidden_criteria == []
    assert triage.pending_proposals == 1
    assert (triage.last_run_scenario, triage.last_run_version, triage.last_run_ms) == ("s-02", 2, 40)
    assert triage.last_run_at == "2026-09-10T09:00:03+00:00"

    incident = summary.procedures[0]
    assert incident.promoted_version is None
    assert incident.open_forbidden == 2
    assert incident.open_forbidden_criteria == ["never_general", "not_resolved_in_first_post"]


def test_tool_call_and_latency_metrics(seeded: Path):
    store = LocalRunStore(seeded)
    m = measure([t for v in (1, 2) for t in store.list_runs(TRIAGE, v)])
    assert m.runs == 4 and m.tool_calls == 7 and m.calls_per_run == 1.75
    assert m.by_tool == {"jira.create_issue": 2, "kb.search": 3, "slack.post": 2}
    assert m.tool_ms_mean == 3.57 and m.tool_ms_p95 == 9 and m.tool_ms_max == 9
    assert m.run_ms_mean == 25.0 and m.run_ms_total == 100
    assert measure([]).tool_calls == 0

    text = format_ops(collect_ops(store))
    assert (
        "2 procedure(s), 3 prompt version(s), 4 scenario(s), 2 open forbidden action(s), 5 run(s), 9 tool call(s)"
        in text
    )
    assert "versions: v1 v2 (latest v2, promoted v2)" in text
    assert "pass rate: v1 50.0%, v2 100.0%" in text
    assert "open forbidden actions: 2 (never_general, not_resolved_in_first_post)" in text
    assert "last run: s-02 on v2 at 2026-09-10T09:00:03+00:00 in 40 ms" in text
    assert "runs: 4, tool calls 7 (1.75 per run), tool latency mean 3.57 ms, p95 9 ms, max 9 ms" in text
    assert "tools: jira.create_issue 2, kb.search 3, slack.post 2" in text


def test_run_artifact_records_versions_and_metrics(seeded: Path, tmp_path: Path):
    store = LocalRunStore(seeded)
    reports = [store.load_report(TRIAGE, v) for v in (1, 2)]
    traces = [t for v in (1, 2) for t in store.list_runs(TRIAGE, v)]
    path = write_run_artifact(tmp_path / "artifacts", "loop", TRIAGE, reports, traces, {"stop_reason": "all pass"})

    data = json.loads(path.read_text())
    assert path.name == f"{data['artifact_id']}.json" and data["artifact_id"].startswith("loop-")
    assert data["command"] == "loop" and data["procedure"] == TRIAGE
    assert data["stop_reason"] == "all pass"
    assert [v["version"] for v in data["versions"]] == [1, 2]
    assert data["versions"][0] == {
        "version": 1,
        "scenarios": 2,
        "passed": 1,
        "pass_rate": 0.5,
        "mean_score": 0.75,
        "forbidden_violations": 1,
        "failing": ["s-02"],
    }
    assert data["metrics"]["tool_calls"] == 7 and data["metrics"]["by_tool"]["kb.search"] == 3
    assert data["metrics"]["run_ms_total"] == 100


def test_cli_eval_writes_an_artifact_and_ops_reads_it(
    settings: Settings, triage_dir: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("PLAYBOOK_FAKE_MODEL_URL", settings.anthropic_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_JIRA_URL", settings.jira_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_SLACK_URL", settings.slack_base_url)
    runs = tmp_path / "ops-runs"
    cli = CliRunner()
    r = cli.invoke(main, ["eval", str(triage_dir), "--runs-dir", str(runs)])
    assert r.exit_code == 0, r.output

    artifacts = sorted((runs / "support-triage" / "artifacts").glob("eval-*.json"))
    assert len(artifacts) == 1
    data = json.loads(artifacts[0].read_text())
    assert data["versions"][0]["scenarios"] == 16 and data["metrics"]["runs"] == 16

    r = cli.invoke(main, ["ops", "--runs-dir", str(runs)])
    assert r.exit_code == 0, r.output
    assert "1 procedure(s), 1 prompt version(s), 16 scenario(s)" in r.output
    assert "support-triage" in r.output and "nothing promoted" in r.output
    assert f"tool calls {data['metrics']['tool_calls']}" in r.output
