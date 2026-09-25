from pathlib import Path

from playbook.agent.prompt import Correction
from playbook.config import Settings
from playbook.evals.report import build_report, compare, format_table
from playbook.feedback.corrections import derive_corrections
from playbook.feedback.loop import improve_once, run_loop
from playbook.runner import Runner, Workspace


def _runner(settings: Settings, procedure_dir: Path) -> Runner:
    ws = Workspace(procedure_dir, settings.runs_dir)
    ws.ingest()
    return Runner(settings, ws)


def test_corrections_change_the_prompt_and_fix_a_failing_scenario(settings: Settings, triage_dir: Path):
    runner = _runner(settings, triage_dir)
    scenarios = runner.ws.scenarios()
    v1 = runner.ws.prompt()
    runner.reset_fakes()
    report_v1 = runner.run_version(v1)
    first = next(g for g in report_v1.grades if g.scenario_id == "triage-01")
    assert not first.passed
    failed_ids = {r.id for r in first.failed()}
    assert {"summary_prefixed", "priority_matches_matrix", "oncall_paged_for_sev1", "no_pii_in_slack"} <= failed_ids

    corrections = derive_corrections(report_v1.grades, scenarios, runner.rubric, v1.version)
    texts = {c.text for c in corrections}
    assert 'When severity is sev1, set priority to "Highest".' in texts
    assert 'When severity is sev2 and tier is enterprise, set priority to "Highest".' in texts
    assert "When tier is enterprise, post to #support-escalations mentioning the issue key." in texts
    assert "When posting to Slack, do not include the customer email." in texts
    assert all(c.evidence.startswith("failed in v1 on triage-") for c in corrections)

    v2 = improve_once(runner, v1, report_v1)
    assert v2 is not None and v2.version == 2
    assert v1.render(runner.procedure) != v2.render(runner.procedure)
    assert runner.store.prompt_versions(runner.procedure.slug) == [1, 2]
    runner.reset_fakes()
    trace = runner.run_scenario(v2, scenarios.get("triage-01"))
    grade = runner.grade(trace, scenarios.get("triage-01"))
    assert grade.passed, [r.rationale for r in grade.failed()]
    assert trace.calls("jira.create_issue")[0].args["priority"] == "Highest"
    assert any(c.args["channel"] == "#oncall-sev1" for c in trace.calls("slack.post"))


def test_loop_keeps_every_version_and_stops_at_plateau(settings: Settings, incident_dir: Path):
    runner = _runner(settings, incident_dir)
    result = run_loop(runner, runner.ws.prompt(), max_rounds=4)
    rates = [r.report.pass_rate for r in result.rounds]
    assert rates[0] < rates[-1] == 1.0
    assert result.stop_reason == "all scenarios pass"
    versions = list(range(1, len(result.rounds) + 1))
    assert runner.store.prompt_versions(runner.procedure.slug) == versions
    assert runner.store.report_versions(runner.procedure.slug) == versions
    last = result.rounds[-1]
    assert last.comparison is not None and last.comparison.newly_failing == []
    assert last.comparison.pass_rate_delta > 0
    stored = runner.store.list_runs(runner.procedure.slug, last.spec.version)
    assert len(stored) == len(runner.ws.scenarios().scenarios)
    table = format_table(result.reports)
    assert "pass rate" in table and "status_updates_when_customer_facing" in table


def test_regression_comparison_flags_newly_failing(settings: Settings, triage_dir: Path):
    runner = _runner(settings, triage_dir)
    v1 = runner.ws.prompt()
    runner.reset_fakes()
    before = runner.run_version(v1)
    # A bad correction that breaks a scenario which passed in v1 (triage-10: sev3, no KB match).
    bad = v1.with_corrections(
        [Correction("set-state", 'When severity is sev3, transition to "Done".', "bad", 1)], notes="regression"
    )
    runner.reset_fakes()
    after = runner.run_version(bad)
    cmp_ = compare(before, after)
    assert cmp_.regressed
    assert cmp_.newly_failing == ["triage-10"]
    assert cmp_.pass_rate_delta < 0
    assert cmp_.criterion_deltas["never_done"] < 0
    assert cmp_.criterion_deltas["kb_searched"] == 0
    reloaded = runner.ws.report(after.prompt_version)
    assert build_report(reloaded.grades, runner.rubric).pass_rate == after.pass_rate
    grades = runner.store.list_grades(runner.procedure.slug, after.prompt_version)
    assert [g.scenario_id for g in grades] == sorted(g.scenario_id for g in after.grades)
    assert not next(g for g in grades if g.scenario_id == "triage-10").passed
