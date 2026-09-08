"""The `playbook` command line."""

from __future__ import annotations

import getpass
import json
import os
import signal
import sys
import threading
from pathlib import Path

import click
import httpx

from playbook.config import FAKE_JIRA_PORT, FAKE_MODEL_PORT, FAKE_SLACK_PORT, Settings
from playbook.evals.coverage import coverage, format_coverage
from playbook.evals.report import VersionReport, compare, format_table
from playbook.evals.scenarios import ScenarioSet
from playbook.evals.synthesis import synthesize as synthesize_scenarios
from playbook.feedback.corrections import derive_corrections
from playbook.feedback.loop import improve_once, propose, run_loop
from playbook.feedback.review import AUTO_REVIEWER, Proposal, ReviewQueue, format_review
from playbook.runner import Runner, Workspace

_procedure_arg = click.argument("procedure_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
_live_opt = click.option("--live", is_flag=True, help="Use the real Anthropic API, Jira and Slack.")
_runs_opt = click.option(
    "--runs-dir",
    type=click.Path(path_type=Path),
    default=None,
    envvar="PLAYBOOK_RUNS_DIR",
    help="Where prompts, runs and reports are written (default ./runs).",
)
_scenarios_opt = click.option(
    "--scenarios",
    "scenarios_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Scenario set to use instead of the procedure's scenarios.yaml (for example a synthesized set).",
)


_reviewer_opt = click.option(
    "--as",
    "reviewer",
    default=None,
    envvar="PLAYBOOK_REVIEWER",
    help="Reviewer name recorded on the decision (default PLAYBOOK_REVIEWER or the login name).",
)


def _reviewer(name: str | None) -> str:
    return name or os.environ.get("PLAYBOOK_REVIEWER") or getpass.getuser()


def _settings(live: bool, runs_dir: Path | None) -> Settings:
    settings = Settings.from_env(live=live)
    if runs_dir is not None:
        settings = Settings(**{**settings.__dict__, "runs_dir": runs_dir})
    return settings


def _workspace(procedure_dir: Path, settings: Settings) -> Workspace:
    ws = Workspace(procedure_dir, settings.runs_dir)
    if not (ws.out_dir / "procedure.json").exists():
        ws.ingest()
    return ws


@click.group()
@click.version_option(package_name="playbook")
def main() -> None:
    """Expert SOP to deployed tool-calling agent, with rubric evals and a feedback loop."""


@main.command()
@_procedure_arg
@_runs_opt
def ingest(procedure_dir: Path, runs_dir: Path | None) -> None:
    """Parse sop.md and walkthrough.md into a structured procedure with citations."""
    ws = Workspace(procedure_dir, runs_dir or Path("runs"))
    proc, path = ws.ingest()
    click.echo(
        f"{proc.name} ({proc.slug}): {len(proc.steps)} steps, "
        f"{len(proc.decision_points)} decision points, {len(proc.forbidden)} prohibitions"
    )
    for s in proc.steps:
        click.echo(f"  {s.index}. {s.title} [{s.id}] tool={s.tool} ({s.citation})")
    for d in proc.decision_points:
        click.echo(f"  {d.kind:9s} -> {d.step_id or '-':16s} {d.text} ({d.citation})")
    click.echo(f"wrote {path}")


@main.command()
@_procedure_arg
@click.option("--version", "version", type=int, default=None, help="Prompt version (default latest).")
@click.option("--scenario", "scenario_id", default=None, help="Run one scenario id only.")
@_live_opt
@_runs_opt
def run(
    procedure_dir: Path,
    version: int | None,
    scenario_id: str | None,
    live: bool,
    runs_dir: Path | None,
) -> None:
    """Run the agent on the scenario set (or one scenario) and store the traces."""
    settings = _settings(live, runs_dir)
    ws = _workspace(procedure_dir, settings)
    runner = Runner(settings, ws, log=click.echo)
    spec = ws.prompt(version)
    scenarios = ws.scenarios()
    targets = [scenarios.get(scenario_id)] if scenario_id else scenarios.scenarios
    for sc in targets:
        trace = runner.run_scenario(spec, sc)
        click.echo(f"{spec.label} {sc.id}: {trace.status}, {len(trace.tool_calls)} tool calls")
        for c in trace.tool_calls:
            click.echo(f"    {c.name} {json.dumps(c.args)[:110]}")


@main.command(name="eval")
@_procedure_arg
@click.option("--version", "version", type=int, default=None, help="Prompt version (default latest).")
@click.option("--regrade", is_flag=True, help="Grade stored traces instead of re-running the agent.")
@click.option("--compare", "compare_to", type=int, default=None, help="Compare with this version.")
@_scenarios_opt
@_live_opt
@_runs_opt
def eval_cmd(
    procedure_dir: Path,
    version: int | None,
    regrade: bool,
    compare_to: int | None,
    scenarios_path: Path | None,
    live: bool,
    runs_dir: Path | None,
) -> None:
    """Grade a prompt version against the expert rubric."""
    settings = _settings(live, runs_dir)
    ws = _workspace(procedure_dir, settings)
    runner = Runner(settings, ws, log=click.echo)
    spec = ws.prompt(version)
    if regrade:
        report = runner.regrade_version(spec.version)
    else:
        runner.reset_fakes()
        report = runner.run_version(spec, ScenarioSet.load(scenarios_path) if scenarios_path else None)
    reports = [report]
    if compare_to is not None:
        before = VersionReport.load(ws.reports_dir, compare_to)
        reports.insert(0, before)
        cmp_ = compare(before, report)
        click.echo(f"newly passing: {cmp_.newly_passing or '-'}; newly failing: {cmp_.newly_failing or '-'}")
    click.echo(format_table(reports))
    for g in report.grades:
        if not g.passed:
            failed = ", ".join(f"{r.id} ({r.rationale})" for r in g.failed())
            click.echo(f"  FAIL {g.scenario_id}: {failed}")


@main.command()
@_procedure_arg
@click.option("--version", "version", type=int, default=None, help="Version to improve (default latest).")
@click.option("--dry-run", is_flag=True, help="Print the corrections without recording proposals.")
@click.option("--auto-approve", is_flag=True, help=f"Approve every pending proposal as reviewer '{AUTO_REVIEWER}'.")
@_runs_opt
def improve(procedure_dir: Path, version: int | None, dry_run: bool, auto_approve: bool, runs_dir: Path | None) -> None:
    """Record the failures in a graded version as proposals and build the next version from the approved ones."""
    settings = _settings(False, runs_dir)
    ws = _workspace(procedure_dir, settings)
    spec = ws.prompt(version)
    report_path = ws.reports_dir / f"{spec.label}.json"
    if not report_path.exists():
        raise click.ClickException(f"no report for {spec.label}; run `playbook eval` first")
    report = VersionReport.load(ws.reports_dir, spec.version)
    if dry_run:
        for c in derive_corrections(report.grades, ws.scenarios(), ws.rubric(), spec.version):
            click.echo(f"  [{c.step_id}] {c.text}  ({c.criterion}; {c.evidence})")
        return
    runner = Runner(settings, ws, log=click.echo)
    added = propose(runner, spec, report)
    if added:
        click.echo(f"recorded {len(added)} new proposal(s) from {spec.label}")
    new = improve_once(runner, spec, report, reviewer=AUTO_REVIEWER if auto_approve else None)
    if new is None:
        pending = ReviewQueue(runner.store, runner.procedure.slug).pending(spec.version)
        if pending:
            click.echo(f"{len(pending)} proposal(s) pending review; run `playbook review list` then approve or reject")
            _print_proposals(pending)
        else:
            click.echo("no approved corrections to apply; prompt unchanged")
        return
    click.echo(f"created {new.label} with {len(new.corrections) - len(spec.corrections)} approved correction(s):")
    for c in new.corrections:
        if c.version == new.version:
            click.echo(f"  {c.proposal_id} [{c.step_id}] {c.text}  ({c.criterion}; {c.evidence})")


def _print_proposals(proposals: list[Proposal]) -> None:
    for p in proposals:
        click.echo(f"  {p.id} {p.status:<8s} [{p.step_id}] {p.final_text}  ({p.criterion}; {p.evidence})")


@main.group()
def review() -> None:
    """Approve, edit or reject the corrections proposed for a prompt version."""


@review.command(name="list")
@_procedure_arg
@click.option("--version", "version", type=int, default=None, help="Source version (default all).")
@click.option("--all", "show_all", is_flag=True, help="Include decided proposals.")
@_runs_opt
def review_list(procedure_dir: Path, version: int | None, show_all: bool, runs_dir: Path | None) -> None:
    """List proposals with their evidence."""
    settings = _settings(False, runs_dir)
    ws = _workspace(procedure_dir, settings)
    queue = ReviewQueue(Runner(settings, ws).store, ws.slug)
    items = queue.all(version) if show_all else queue.pending(version)
    if not items:
        click.echo("no proposals" if show_all else "no pending proposals")
        return
    _print_proposals(items)


def _decide(procedure_dir: Path, runs_dir: Path | None, proposal_id: str, status: str, reviewer: str | None, **kw):
    settings = _settings(False, runs_dir)
    ws = _workspace(procedure_dir, settings)
    queue = ReviewQueue(Runner(settings, ws).store, ws.slug)
    try:
        p = queue.decide(proposal_id, status, _reviewer(reviewer), **kw)
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"{p.id} {p.status} by {p.reviewer}: [{p.step_id}] {p.final_text}")


@review.command()
@_procedure_arg
@click.argument("proposal_id")
@click.option("--note", default="", help="Reviewer note.")
@_reviewer_opt
@_runs_opt
def approve(procedure_dir: Path, proposal_id: str, note: str, reviewer: str | None, runs_dir: Path | None) -> None:
    """Approve a proposal as written."""
    _decide(procedure_dir, runs_dir, proposal_id, "approved", reviewer, note=note)


@review.command()
@_procedure_arg
@click.argument("proposal_id")
@click.option("--text", required=True, help="The rule text to apply instead of the proposed one.")
@click.option("--note", default="", help="Reviewer note.")
@_reviewer_opt
@_runs_opt
def edit(
    procedure_dir: Path, proposal_id: str, text: str, note: str, reviewer: str | None, runs_dir: Path | None
) -> None:
    """Approve a proposal with edited text; the edited text is what enters the prompt."""
    _decide(procedure_dir, runs_dir, proposal_id, "approved", reviewer, note=note, text=text)


@review.command()
@_procedure_arg
@click.argument("proposal_id")
@click.option("--note", default="", help="Why it was rejected.")
@_reviewer_opt
@_runs_opt
def reject(procedure_dir: Path, proposal_id: str, note: str, reviewer: str | None, runs_dir: Path | None) -> None:
    """Reject a proposal; it never enters a prompt."""
    _decide(procedure_dir, runs_dir, proposal_id, "rejected", reviewer, note=note)


@review.command(name="report")
@_procedure_arg
@click.option("--version", "version", type=int, default=None, help="Source version (default every version).")
@_runs_opt
def review_report(procedure_dir: Path, version: int | None, runs_dir: Path | None) -> None:
    """Per-version review report: proposed, approved, edited, rejected, pending and applied."""
    settings = _settings(False, runs_dir)
    ws = _workspace(procedure_dir, settings)
    queue = ReviewQueue(Runner(settings, ws).store, ws.slug)
    versions = [version] if version is not None else sorted({p.source_version for p in queue.all()})
    if not versions:
        click.echo("no proposals recorded")
        return
    for v in versions:
        click.echo(format_review(queue.report(v)))


@main.command()
@_procedure_arg
@click.option("--max-rounds", type=int, default=5, show_default=True)
@click.option("--start-version", type=int, default=None, help="Start from this version (default latest).")
@click.option(
    "--review",
    "require_review",
    is_flag=True,
    help=f"Stop when proposals await an expert instead of approving them as '{AUTO_REVIEWER}'.",
)
@_live_opt
@_runs_opt
def loop(
    procedure_dir: Path,
    max_rounds: int,
    start_version: int | None,
    require_review: bool,
    live: bool,
    runs_dir: Path | None,
) -> None:
    """Run, grade, correct and re-run until the pass rate plateaus. Every version is kept."""
    settings = _settings(live, runs_dir)
    ws = _workspace(procedure_dir, settings)
    runner = Runner(settings, ws, log=click.echo)
    reviewer = None if require_review else AUTO_REVIEWER
    result = run_loop(runner, ws.prompt(start_version), max_rounds=max_rounds, reviewer=reviewer)
    click.echo("")
    for rd in result.rounds:
        for c in rd.corrections:
            click.echo(f"{rd.spec.label} [{c.step_id}] {c.text}  ({c.evidence})")
    click.echo("")
    click.echo(format_table(result.reports))
    click.echo(f"stopped: {result.stop_reason}")
    if result.pending:
        _print_proposals(result.pending)


@main.command()
@_procedure_arg
@click.option("--versions", default=None, help="Comma separated versions (default all).")
@click.option("--inbox", is_flag=True, help="Also print the fake Jira and Slack inboxes.")
@_runs_opt
def report(procedure_dir: Path, versions: str | None, inbox: bool, runs_dir: Path | None) -> None:
    """Print the before/after table for stored reports."""
    settings = _settings(False, runs_dir)
    ws = _workspace(procedure_dir, settings)
    if versions:
        wanted = [int(v) for v in versions.split(",")]
    else:
        wanted = sorted(int(p.stem[1:]) for p in ws.reports_dir.glob("v*.json"))
    if not wanted:
        raise click.ClickException("no reports found; run `playbook eval` or `playbook loop`")
    reports = [VersionReport.load(ws.reports_dir, v) for v in wanted]
    click.echo(format_table(reports))
    if len(reports) > 1:
        cmp_ = compare(reports[0], reports[-1])
        click.echo(f"newly passing: {', '.join(cmp_.newly_passing) or '-'}")
        click.echo(f"newly failing: {', '.join(cmp_.newly_failing) or '-'}")
    if inbox:
        _print_inbox(settings)


def _print_inbox(settings: Settings) -> None:
    try:
        jira = httpx.get(settings.jira_base_url + "/_inbox", timeout=5).json()
        slack = httpx.get(settings.slack_base_url + "/_inbox", timeout=5).json()
    except httpx.HTTPError as exc:
        click.echo(f"(fakes not reachable: {exc})")
        return
    click.echo(f"\nJira inbox: {len(jira['issues'])} issues")
    for key, issue in list(jira["issues"].items())[:6]:
        f = issue["fields"]
        click.echo(
            f"  {key} [{f['priority']['name']}] {f['summary']} -> {f['status']['name']} "
            f"({len(issue.get('comments', []))} comment)"
        )
    click.echo(f"Slack inbox: {len(slack['messages'])} messages")
    for m in slack["messages"][:6]:
        click.echo(f"  {m['channel']}: {m['text']}")


@main.command(name="coverage")
@_procedure_arg
@_scenarios_opt
@click.option("--strict", is_flag=True, help="Exit non-zero when a branch or criterion is uncovered.")
@_runs_opt
def coverage_cmd(procedure_dir: Path, scenarios_path: Path | None, strict: bool, runs_dir: Path | None) -> None:
    """Report which walkthrough decision branches and rubric criteria the scenario set exercises."""
    settings = _settings(False, runs_dir)
    ws = _workspace(procedure_dir, settings)
    scenarios = ScenarioSet.load(scenarios_path) if scenarios_path else ws.scenarios()
    report = coverage(ws.procedure(), scenarios, ws.rubric())
    click.echo(format_coverage(report))
    if strict and report.flagged:
        raise click.ClickException("uncovered branches or criteria; run `playbook synthesize --only-uncovered`")


@main.command()
@_procedure_arg
@click.option("--only-uncovered", is_flag=True, help="Add scenarios only for branches no scenario covers.")
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=None, help="Output YAML path.")
@_runs_opt
def synthesize(procedure_dir: Path, only_uncovered: bool, out_path: Path | None, runs_dir: Path | None) -> None:
    """Derive scenarios from the walkthrough decision points, one per branch, and write a scenario set."""
    settings = _settings(False, runs_dir)
    ws = _workspace(procedure_dir, settings)
    proc, rubric = ws.procedure(), ws.rubric()
    result = synthesize_scenarios(proc, ws.scenarios(), rubric, only_uncovered=only_uncovered)
    out = out_path or ws.out_dir / "scenarios.synth.yaml"
    header = (
        f"Synthesized from {proc.sources[-1]} decision points: {result.branches_added} scenario(s) added to "
        f"{len(ws.scenarios().scenarios)} hand-written. Expected values are inferred from scenarios that share "
        "the rubric's condition variables; needs-expert tags mark the ones to confirm."
    )
    result.scenarios.save(out, header)
    for sc in result.added:
        note = f"  needs expert: {', '.join(result.needs_expert[sc.id])}" if sc.id in result.needs_expert else ""
        click.echo(f"  {sc.id:<14s} {' '.join(t for t in sc.tags if '=' in t)}{note}")
    after = coverage(proc, result.scenarios, rubric)
    click.echo(
        f"{result.branches_added} scenario(s) synthesized, {len(result.needs_expert)} need expert confirmation; "
        f"{after.branches_covered}/{after.branches_total} branches covered; wrote {out}"
    )


@main.command(name="serve-fakes")
@click.option("--model-port", type=int, default=FAKE_MODEL_PORT, show_default=True)
@click.option("--jira-port", type=int, default=FAKE_JIRA_PORT, show_default=True)
@click.option("--slack-port", type=int, default=FAKE_SLACK_PORT, show_default=True)
def serve_fakes(model_port: int, jira_port: int, slack_port: int) -> None:
    """Serve the offline Messages API, Jira and Slack stand-ins until interrupted."""
    from fakes import jira_server, model_server, slack_server

    servers = [
        model_server.serve(model_port),
        jira_server.serve(jira_port),
        slack_server.serve(slack_port),
    ]
    for name, s in zip(("model", "jira", "slack"), servers, strict=True):
        click.echo(f"fake {name}: {s.url}")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    for s in servers:
        s.stop()


if __name__ == "__main__":
    sys.exit(main())
