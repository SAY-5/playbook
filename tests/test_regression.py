import json
from pathlib import Path

from click.testing import CliRunner

from playbook.agent.prompt import Correction
from playbook.agent.store import LocalRunStore
from playbook.cli import main
from playbook.config import Settings
from playbook.evals.bank import ScenarioBank, format_bank
from playbook.evals.regression import format_regression, run_regression
from playbook.evals.report import VersionReport
from playbook.evals.scenarios import Scenario, ScenarioSet
from playbook.feedback.loop import run_loop
from playbook.runner import Runner, Workspace

BAD = Correction("set-state", 'When severity is sev3, transition to "Done".', "never_done", 1)


def _runner(settings: Settings, procedure_dir: Path) -> Runner:
    ws = Workspace(procedure_dir, settings.runs_dir)
    ws.ingest()
    return Runner(settings, ws)


def _bank_of(runner: Runner, reports: list[VersionReport]) -> ScenarioBank:
    bank = ScenarioBank(runner.procedure.slug)
    bank.add(runner.ws.scenarios())
    for report in reports:
        bank.record(report.prompt_version, {g.scenario_id: g.passed for g in report.grades})
    return bank


def _probe() -> Scenario:
    """A brand new case the bank has never scored, whose expected priority the SOP will not meet."""
    return Scenario(
        id="triage-probe",
        intake={
            "kind": "support request",
            "account": "ACC-9001",
            "tier": "pro",
            "severity": "sev2",
            "title": "Weekly report export stalls at 90 percent",
            "report": "The weekly export stops at 90 percent and never finishes.",
        },
        expected={
            "priority": "Highest",
            "escalate": False,
            "page_oncall": False,
            "kb_hit": False,
            "final_status": "Triaged",
        },
        tags=["sev2", "probe"],
    )


def test_guard_catches_a_regressed_version(settings: Settings, triage_dir: Path):
    runner = _runner(settings, triage_dir)
    v1 = runner.ws.prompt()
    runner.reset_fakes()
    report_v1 = runner.run_version(v1)
    bank = _bank_of(runner, [report_v1])
    assert bank.get("triage-10").outcomes == {1: True}

    regressed = v1.with_corrections([BAD], notes="a correction that breaks a passing case")
    runner.reset_fakes()
    result = run_regression(runner, regressed, bank)
    assert not result.guard_passed
    assert result.broken == ["triage-10"]
    assert "triage-10" not in result.still_failing and result.new_failing == []
    assert next(o for o in result.outcomes if o.scenario_id == "triage-10").baseline_version == 1

    text = format_regression(result)
    assert "GUARD FAILED: 1 scenario(s) regressed" in text and "broken: triage-10" in text


def test_guard_passes_when_only_new_scenarios_fail(settings: Settings, triage_dir: Path):
    runner = _runner(settings, triage_dir)
    loop = run_loop(runner, runner.ws.prompt(), max_rounds=4)
    bank = _bank_of(runner, loop.reports)
    bank.add(ScenarioSet(runner.procedure.slug, [_probe()]), source="probe.yaml")
    latest = loop.rounds[-1].spec

    runner.reset_fakes()
    result = run_regression(runner, latest, bank)
    assert result.new_failing == ["triage-probe"]
    assert result.broken == [] and result.guard_passed
    assert sorted(result.fixed) == ["triage-05", "triage-12"]

    rates = {t.tag: (t.passed, t.total) for t in result.per_tag()}
    assert rates["sev1"] == (4, 4)
    assert rates["enterprise"] == (6, 6)
    assert rates["probe"] == (0, 1)
    assert rates["sev2"] == (5, 6)
    assert "per tag:" in format_regression(result) and "guard passed" in format_regression(result)


def test_bank_merges_sets_and_keeps_history(settings: Settings, triage_dir: Path, tmp_path: Path):
    ws = Workspace(triage_dir, settings.runs_dir)
    ws.ingest()
    bank = ScenarioBank(ws.slug)
    assert len(bank.add(ws.scenarios())) == 16
    bank.record(1, {"triage-01": False, "triage-10": True, "unknown": False})
    assert bank.add(ws.scenarios()) == []
    assert bank.add(ScenarioSet(ws.slug, [_probe()]), source="probe.yaml") == ["triage-probe"]

    assert [e.id for e in bank.historical_failures()] == ["triage-01"]
    assert [e.id for e in bank.select(failures_only=True)] == [e.id for e in bank.entries if e.id not in ("triage-10",)]
    assert [e.id for e in bank.by_tag("probe")] == ["triage-probe"]

    store = LocalRunStore(tmp_path)
    assert store.save_bank(bank) == str(tmp_path / ws.slug / "bank.json")
    again = store.load_bank(ws.slug)
    assert again.get("triage-10").outcomes == {1: True}
    assert again.get("triage-probe").added_from == "probe.yaml"
    assert len(again.entries) == 17
    assert store.load_bank("never-banked").entries == []

    text = format_bank(bank)
    assert "17 scenario(s)" in text and "historical failures: triage-01" in text


def test_cli_regress_fails_the_run_on_a_regression(settings: Settings, triage_dir: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLAYBOOK_FAKE_MODEL_URL", settings.anthropic_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_JIRA_URL", settings.jira_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_SLACK_URL", settings.slack_base_url)
    runs = tmp_path / "regress-runs"
    where = ["--runs-dir", str(runs)]
    cli = CliRunner()
    assert cli.invoke(main, ["eval", str(triage_dir), *where]).exit_code == 0

    # A reviewer proposes the bad rule; approving it and running improve makes it v2.
    propose = ["review", "propose", str(triage_dir), *where, "--step", "set-state"]
    r = cli.invoke(main, [*propose, "--text", BAD.text, "--as", "dana"])
    assert r.exit_code == 0, r.output
    assert "p1-" in r.output and "proposed by dana" in r.output
    r = cli.invoke(main, ["review", "propose", str(triage_dir), *where, "--step", "nowhere", "--text", "x"])
    assert r.exit_code != 0 and "unknown step nowhere" in r.output
    listed = cli.invoke(main, ["review", "list", str(triage_dir), *where]).output
    proposal_id = next(line.split()[0] for line in listed.splitlines() if BAD.text in line)
    assert cli.invoke(main, ["review", "approve", str(triage_dir), *where, proposal_id, "--as", "dana"]).exit_code == 0
    r = cli.invoke(main, ["improve", str(triage_dir), *where])
    assert r.exit_code == 0, r.output
    assert "created v2 with 1 approved correction(s)" in r.output and BAD.text in r.output
    ws = Workspace(triage_dir, runs)
    assert [c.text for c in ws.prompt(2).corrections] == [BAD.text]

    r = cli.invoke(main, ["bank", str(triage_dir), *where])
    assert r.exit_code == 0, r.output
    assert "added 16 scenario(s)" in r.output and "16 scenario(s), 11 tag(s), versions v1" in r.output

    r = cli.invoke(main, ["regress", str(triage_dir), *where, "--tag", "sev3"])
    assert r.exit_code == 1
    assert "GUARD FAILED" in r.output and "broken: triage-10" in r.output
    assert "sev3              " in r.output
    artifact = json.loads(next((runs / "support-triage" / "artifacts").glob("regress-*.json")).read_text())
    assert artifact["regression"]["guard_passed"] is False and artifact["regression"]["broken"] == ["triage-10"]
    assert [v["version"] for v in artifact["versions"]] == [2]
    assert artifact["versions"][0]["scenarios"] == 4 and "triage-10" in artifact["versions"][0]["failing"]
