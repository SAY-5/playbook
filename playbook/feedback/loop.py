"""Run, grade, correct, re-run: iterate prompt versions until the pass rate plateaus."""

from __future__ import annotations

from dataclasses import dataclass, field

from playbook.agent.prompt import Correction, PromptSpec
from playbook.evals.report import Comparison, VersionReport, compare
from playbook.feedback.corrections import derive_corrections
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

    @property
    def reports(self) -> list[VersionReport]:
        return [r.report for r in self.rounds]


def improve_once(runner: Runner, spec: PromptSpec, report: VersionReport) -> PromptSpec | None:
    """Create the next prompt version from this report's failures, or None if nothing applies."""
    corrections = derive_corrections(report.grades, runner.ws.scenarios(), runner.rubric, spec.version)
    if not corrections:
        return None
    new = spec.with_corrections(
        corrections,
        notes=f"{len(corrections)} correction(s) from v{spec.version} failures "
        f"(pass rate {report.pass_rate:.0%})",
    )
    if len(new.corrections) == len(spec.corrections):
        return None
    new.save(runner.ws.prompts_dir)
    return new


def run_loop(
    runner: Runner,
    start: PromptSpec,
    *,
    max_rounds: int = 5,
    min_delta: float = 0.0,
) -> LoopResult:
    runner.reset_fakes()
    runner.log(f"running {start.label}")
    spec = start
    report = runner.run_version(spec)
    rounds = [Round(spec=spec, report=report)]
    reason = "max rounds reached"
    for _ in range(max_rounds):
        if report.pass_rate >= 1.0:
            reason = "all scenarios pass"
            break
        new = improve_once(runner, spec, report)
        if new is None:
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
