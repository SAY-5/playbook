from pathlib import Path

from click.testing import CliRunner

from playbook.cli import main
from playbook.config import Settings
from playbook.evals.coverage import branch_values, coverage, extract_branches, format_coverage
from playbook.evals.rubric import Rubric
from playbook.evals.scenarios import ScenarioSet
from playbook.evals.synthesis import synthesize
from playbook.ingest import ingest_procedure
from playbook.runner import Runner, Workspace


def _load(procedure_dir: Path):
    return (
        ingest_procedure(procedure_dir),
        ScenarioSet.load(procedure_dir / "scenarios.yaml"),
        Rubric.load(procedure_dir / "rubric.yaml"),
    )


def test_branches_come_from_walkthrough_decisions(triage_dir: Path):
    proc, _, _ = _load(triage_dir)
    assert branch_values("sev1 is Highest, sev2 is High, sev3 is Medium, sev4 is Low.") == {
        "severity": ["sev1", "sev2", "sev3", "sev4"]
    }
    assert branch_values("If a KB article resolves it, the ticket goes to Waiting for Customer.") == {
        "kb_hit": [True, False]
    }
    assert branch_values("The Slack post must name the ticket key.") == {}
    by_decision: dict[str, list[str]] = {}
    for b in extract_branches(proc):
        by_decision.setdefault(b.decision_id, []).append(b.label)
    matrix = next(d for d in proc.decision_points if "sev1 is Highest" in d.text)
    assert by_decision[matrix.id] == ["severity=sev1", "severity=sev2", "severity=sev3", "severity=sev4"]
    bump = next(d for d in proc.decision_points if "bumped one level" in d.text)
    assert by_decision[bump.id] == [
        "severity=sev2 and tier=enterprise",
        "severity=sev3 and tier=enterprise",
        "otherwise (severity=sev1 and tier=pro)",
    ]
    otherwise = next(b for b in extract_branches(proc) if b.otherwise)
    scenarios = ScenarioSet.load(triage_dir / "scenarios.yaml")
    assert otherwise.covered_by(scenarios.get("triage-01"))  # enterprise sev1 is not in the exception
    assert not otherwise.covered_by(scenarios.get("triage-05"))  # enterprise sev2 is


def test_sample_sets_cover_every_branch_and_criterion_side(triage_dir: Path, incident_dir: Path):
    for procedure_dir, branches in ((triage_dir, 11), (incident_dir, 8)):
        proc, scenarios, rubric = _load(procedure_dir)
        report = coverage(proc, scenarios, rubric)
        assert (report.branches_total, report.branches_covered) == (branches, branches)
        assert not report.flagged
        assert report.unbranched  # the walkthrough also has unconditional statements
        assert all(c.scenarios > 0 for c in report.criteria)
    triage = coverage(*_load(triage_dir))
    esc = next(c for c in triage.criteria if c.id == "escalated_when_required")
    assert esc.sides == {"expected": 9, "not_expected": 7}
    prio = next(c for c in triage.criteria if c.id == "priority_matches_matrix")
    assert prio.sides == {"Highest": 6, "High": 5, "Medium": 2, "Low": 3}
    pii = next(c for c in triage.criteria if c.id == "no_pii_in_slack")
    assert pii.sides == {"with_pii": 7, "without_pii": 9}
    text = format_coverage(triage)
    assert "11/11 branches covered (100.0%)" in text and "flagged: none" in text
    assert triage.to_dict()["branches_covered"] == 11


def test_reduced_set_is_flagged_and_synthesis_fills_the_gaps(settings: Settings, triage_dir: Path):
    proc, full, rubric = _load(triage_dir)
    small = ScenarioSet(full.procedure_slug, full.scenarios[:3])  # three sev1 requests
    before = coverage(proc, small, rubric)
    assert before.flagged
    assert [b["label"] for _, b in before.uncovered_branches] == [
        "severity=sev2",
        "severity=sev3",
        "severity=sev4",
        "severity=sev2 and tier=enterprise",
        "severity=sev3 and tier=enterprise",
    ]
    assert [c.id for c in before.criterion_gaps] == ["escalated_when_required", "oncall_paged_for_sev1"]
    assert "GAP severity=sev2" in format_coverage(before)

    result = synthesize(proc, small, rubric, only_uncovered=True)
    assert result.branches_added == 5
    after = coverage(proc, result.scenarios, rubric)
    assert after.uncovered_branches == []
    bump = next(s for s in result.added if "severity=sev2" in s.tags and "tier=enterprise" in s.tags)
    assert bump.intake["severity"] == "sev2" and bump.intake["tier"] == "enterprise"
    assert "synthesized" in bump.tags and "template:triage-01" in bump.tags
    # no sev2 scenario exists to vouch for the priority, so the expert has to confirm it
    assert result.needs_expert[bump.id] == ["priority", "escalate", "page_oncall"]
    assert "needs-expert:priority" in bump.tags
    assert bump.expected["final_status"] == "Waiting for Customer"  # inferred from the kb_hit witnesses

    ws = Workspace(triage_dir, settings.runs_dir)
    ws.ingest()
    runner = Runner(settings, ws)
    trace = runner.run_scenario(ws.prompt(), bump)
    assert trace.status == "completed"
    assert "Severity: sev2" in trace.user_message and "Tier: enterprise" in trace.user_message
    assert runner.grade(trace, bump).scenario_id == bump.id


def test_synthesized_set_covers_every_branch_and_round_trips(triage_dir: Path, incident_dir: Path, tmp_path: Path):
    for procedure_dir in (triage_dir, incident_dir):
        proc, scenarios, rubric = _load(procedure_dir)
        result = synthesize(proc, scenarios, rubric)
        assert result.branches_added == coverage(proc, scenarios, rubric).branches_total
        assert result.needs_expert == {}  # the full sets have a witness for every expected value
        ids = [s.id for s in result.scenarios.scenarios]
        assert len(ids) == len(set(ids))
        only_new = ScenarioSet(proc.slug, result.added)
        assert coverage(proc, only_new, rubric).uncovered_branches == []
        path = only_new.save(tmp_path / f"{proc.slug}.yaml", header="synthesized")
        reloaded = ScenarioSet.load(path)
        assert [s.to_dict() for s in reloaded.scenarios] == [s.to_dict() for s in only_new.scenarios]
        assert path.read_text().startswith("# synthesized\n")
    incident = synthesize(*_load(incident_dir))
    cf = next(s for s in incident.added if "customer_facing=false" in s.tags)
    assert cf.intake["customer_facing"] == "no" and cf.expected["customer_facing"] is False


def test_cli_coverage_and_synthesize(settings: Settings, incident_dir: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLAYBOOK_FAKE_MODEL_URL", settings.anthropic_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_JIRA_URL", settings.jira_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_SLACK_URL", settings.slack_base_url)
    runs = tmp_path / "runs"
    cli = CliRunner()
    r = cli.invoke(main, ["coverage", str(incident_dir), "--runs-dir", str(runs), "--strict"])
    assert r.exit_code == 0, r.output
    assert "8/8 branches covered" in r.output and "flagged: none" in r.output
    r = cli.invoke(main, ["synthesize", str(incident_dir), "--runs-dir", str(runs)])
    assert r.exit_code == 0, r.output
    out = runs / "incident_comms" / "scenarios.synth.yaml"
    assert "8 scenario(s) synthesized" in r.output and out.exists()
    small = tmp_path / "small.yaml"
    full = ScenarioSet.load(incident_dir / "scenarios.yaml")
    ScenarioSet(full.procedure_slug, full.scenarios[:3]).save(small)
    args = ["coverage", str(incident_dir), "--runs-dir", str(runs), "--scenarios", str(small), "--strict"]
    r = cli.invoke(main, args)
    assert r.exit_code != 0 and "GAP impact=internal" in r.output
    r = cli.invoke(main, ["eval", str(incident_dir), "--runs-dir", str(runs), "--scenarios", str(out)])
    assert r.exit_code == 0, r.output
    assert "16 scenarios, mode=offline" in r.output
