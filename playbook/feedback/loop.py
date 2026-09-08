"""Run, grade, correct, re-run: iterate prompt versions until the pass rate plateaus."""

from __future__ import annotations

from dataclasses import dataclass, field

from playbook.agent.prompt import Correction, PromptSpec
from playbook.evals.report import Comparison, VersionReport, compare
from playbook.feedback.corrections import derive_corrections
from playbook.feedback.review import AUTO_REVIEWER, Proposal, ReviewQueue
from playbook.runner import Runner


@dataclass
class Round:
    spec: PromptSpec
    report: VersionReport
    corrections: list[Correction] = field(default_factory=list)
    comparison: Comparison | None = None


@dataclass
class LoopResult:
    rounds: list[Round]
    stop_reason: str
    pending: list[Proposal] = field(default_factory=list)

    @property
    def reports(self) -> list[VersionReport]:
        return [r.report for r in self.rounds]


def propose(runner: Runner, spec: PromptSpec, report: VersionReport) -> list[Proposal]:
    """Derive corrections from this report's failures and record the new ones as proposals."""
    corrections = derive_corrections(report.grades, runner.ws.scenarios(), runner.rubric, spec.version)
    return ReviewQueue(runner.store, runner.procedure.slug).propose(corrections, spec.version)


def improve_once(
    runner: Runner, spec: PromptSpec, report: VersionReport, *, reviewer: str | None = AUTO_REVIEWER
) -> PromptSpec | None:
    """Create the next prompt version from the approved proposals for this version.

    New failures are recorded as proposals first. With a `reviewer`, every pending proposal is
    approved under that name (the unattended loop uses `auto`); with `reviewer=None` only proposals
    an expert has already approved are applied. Returns None when nothing approved is left to apply.
    """
    propose(runner, spec, report)
    queue = ReviewQueue(runner.store, runner.procedure.slug)
    if reviewer is not None:
        queue.approve_pending(spec.version, reviewer)
    approved = queue.approved(spec.version)
    if not approved:
        return None
    notes = f"{len(approved)} approved correction(s) from v{spec.version} failures (pass rate {report.pass_rate:.0%})"
    new = spec.with_corrections([p.to_correction() for p in approved], notes=notes)
    if len(new.corrections) == len(spec.corrections):
        return None
    new.save(runner.ws.prompts_dir)
    queue.mark_applied(approved, new.version)
    return new


def run_loop(
    runner: Runner,
    start: PromptSpec,
    *,
    max_rounds: int = 5,
    min_delta: float = 0.0,
    reviewer: str | None = AUTO_REVIEWER,
) -> LoopResult:
    """Iterate versions. With `reviewer=None` the loop stops as soon as proposals await an expert."""
    runner.reset_fakes()
    runner.log(f"running {start.label}")
    spec = start
    report = runner.run_version(spec)
    rounds = [Round(spec=spec, report=report)]
    reason = "max rounds reached"
    queue = ReviewQueue(runner.store, runner.procedure.slug)
    for _ in range(max_rounds):
        if report.pass_rate >= 1.0:
            reason = "all scenarios pass"
            break
        new = improve_once(runner, spec, report, reviewer=reviewer)
        if new is None:
            pending = queue.pending(spec.version)
            if pending:
                reason = f"{len(pending)} proposal(s) from {spec.label} awaiting review"
                return LoopResult(rounds=rounds, stop_reason=reason, pending=pending)
            reason = "no applicable corrections for the remaining failures"
            break
        added = [c for c in new.corrections if c.version == new.version]
        runner.reset_fakes()
        runner.log(f"running {new.label} ({len(added)} new corrections)")
        new_report = runner.run_version(new)
        comparison = compare(report, new_report)
        rounds.append(Round(spec=new, report=new_report, corrections=added, comparison=comparison))
        spec, report = new, new_report
        if comparison.pass_rate_delta <= min_delta:
            reason = f"pass rate plateaued at {report.pass_rate:.0%}"
            break
    return LoopResult(rounds=rounds, stop_reason=reason)
