"""Replay the scenario bank against a prompt version and guard against regressions.

A version that lifts the pass rate can still break a case that used to work. The regression run
replays the banked scenarios, compares each against the last version that scored it, and fails the
run when a previously passing scenario breaks. A scenario the bank has never scored is new, so its
failure is news rather than a regression.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from playbook.agent.prompt import PromptSpec
from playbook.evals.bank import BankEntry, ScenarioBank
from playbook.evals.grader import RunGrade
from playbook.evals.report import VersionReport, build_report
from playbook.evals.rubric import Rubric
from playbook.runner import Runner


@dataclass(frozen=True)
class ScenarioOutcome:
    scenario_id: str
    tags: tuple[str, ...]
    passed: bool
    baseline_version: int | None
    was_passing: bool | None

    @property
    def broke(self) -> bool:
        return self.was_passing is True and not self.passed

    @property
    def fixed(self) -> bool:
        return self.was_passing is False and self.passed

    @property
    def is_new(self) -> bool:
        return self.was_passing is None


@dataclass
class TagRate:
    tag: str
    passed: int
    total: int

    @property
    def rate(self) -> float:
        return round(self.passed / self.total, 4) if self.total else 0.0


@dataclass
class RegressionReport:
    procedure_slug: str
    prompt_version: int
    outcomes: list[ScenarioOutcome] = field(default_factory=list)
    grades: list[RunGrade] = field(default_factory=list)

    def version_report(self, rubric: Rubric) -> VersionReport:
        """The replayed version scored like an eval run, for the run artifact."""
        return build_report(self.grades, rubric)

    @property
    def broken(self) -> list[str]:
        return sorted(o.scenario_id for o in self.outcomes if o.broke)

    @property
    def fixed(self) -> list[str]:
        return sorted(o.scenario_id for o in self.outcomes if o.fixed)

    @property
    def still_failing(self) -> list[str]:
        return sorted(o.scenario_id for o in self.outcomes if o.was_passing is False and not o.passed)

    @property
    def new_failing(self) -> list[str]:
        return sorted(o.scenario_id for o in self.outcomes if o.is_new and not o.passed)

    @property
    def guard_passed(self) -> bool:
        return not self.broken

    @property
    def pass_rate(self) -> float:
        return round(sum(1 for o in self.outcomes if o.passed) / len(self.outcomes), 4) if self.outcomes else 0.0

    @property
    def results(self) -> dict[str, bool]:
        return {o.scenario_id: o.passed for o in self.outcomes}

    def per_tag(self) -> list[TagRate]:
        tags = sorted({t for o in self.outcomes for t in o.tags})
        return [
            TagRate(
                tag,
                sum(1 for o in self.outcomes if tag in o.tags and o.passed),
                sum(1 for o in self.outcomes if tag in o.tags),
            )
            for tag in tags
        ]


def _outcome(entry: BankEntry, version: int, passed: bool) -> ScenarioOutcome:
    baseline = entry.outcome_before(version)
    return ScenarioOutcome(
        scenario_id=entry.id,
        tags=entry.tags,
        passed=passed,
        baseline_version=baseline[0] if baseline else None,
        was_passing=baseline[1] if baseline else None,
    )


def run_regression(
    runner: Runner,
    spec: PromptSpec,
    bank: ScenarioBank,
    *,
    tag: str | None = None,
    failures_only: bool = False,
) -> RegressionReport:
    """Run the selected banked scenarios on `spec` and compare each with its last known outcome."""
    entries = bank.select(tag=tag, failures_only=failures_only)
    if not entries:
        raise ValueError("no banked scenarios match the selection")
    outcomes: list[ScenarioOutcome] = []
    grades: list[RunGrade] = []
    for entry in entries:
        trace = runner.run_scenario(spec, entry.scenario)
        grade = runner.grade(trace, entry.scenario)
        outcome = _outcome(entry, spec.version, grade.passed)
        runner.log(
            f"  {spec.label} {entry.id}: {'pass' if grade.passed else 'FAIL'}{' REGRESSION' if outcome.broke else ''}"
        )
        outcomes.append(outcome)
        grades.append(grade)
    return RegressionReport(
        procedure_slug=runner.procedure.slug, prompt_version=spec.version, outcomes=outcomes, grades=grades
    )


def format_regression(report: RegressionReport) -> str:
    verdict = "guard passed" if report.guard_passed else f"GUARD FAILED: {len(report.broken)} scenario(s) regressed"
    lines = [
        f"{report.procedure_slug} regression of v{report.prompt_version}: {len(report.outcomes)} replayed, "
        f"pass rate {report.pass_rate:.1%}, {len(report.fixed)} fixed, {len(report.broken)} broken, "
        f"{len(report.new_failing)} new failing"
    ]
    for name, ids in (("broken", report.broken), ("fixed", report.fixed), ("new failing", report.new_failing)):
        if ids:
            lines.append(f"  {name}: {', '.join(ids)}")
    lines.append("per tag:")
    for t in report.per_tag():
        lines.append(f"  {t.tag:<16s} {t.passed:>2d}/{t.total:<2d} {t.rate:.1%}")
    lines.append(verdict)
    return "\n".join(lines)
