"""Per-version scoring reports and before/after regression comparison."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from playbook.evals.grader import RunGrade
from playbook.evals.rubric import Rubric


@dataclass
class VersionReport:
    procedure_slug: str
    prompt_version: int
    mode: str
    scenarios: int
    passed: int
    pass_rate: float
    mean_score: float
    per_criterion: dict[str, float]
    required_action_coverage: float
    forbidden_violations: int
    grades: list[RunGrade] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"v{self.prompt_version}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VersionReport:
        return cls(**{**d, "grades": [RunGrade.from_dict(g) for g in d.get("grades", [])]})

    def save(self, reports_dir: Path) -> Path:
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"{self.label}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return path

    @classmethod
    def load(cls, reports_dir: Path, version: int) -> VersionReport:
        return cls.from_dict(json.loads((reports_dir / f"v{version}.json").read_text()))


def build_report(grades: list[RunGrade], rubric: Rubric) -> VersionReport:
    if not grades:
        raise ValueError("no grades to report")
    n = len(grades)
    per_criterion = {
        c.id: round(sum(1 for g in grades for r in g.results if r.id == c.id and r.passed) / n, 4)
        for c in rubric.criteria
    }
    made = sum(g.required_actions_made for g in grades)
    total = sum(g.required_actions_total for g in grades) or 1
    return VersionReport(
        procedure_slug=grades[0].procedure_slug,
        prompt_version=grades[0].prompt_version,
        mode=grades[0].mode,
        scenarios=n,
        passed=sum(1 for g in grades if g.passed),
        pass_rate=round(sum(1 for g in grades if g.passed) / n, 4),
        mean_score=round(sum(g.score for g in grades) / n, 4),
        per_criterion=per_criterion,
        required_action_coverage=round(made / total, 4),
        forbidden_violations=sum(g.forbidden_violations for g in grades),
        grades=grades,
    )


@dataclass
class Comparison:
    before: int
    after: int
    pass_rate_delta: float
    criterion_deltas: dict[str, float]
    newly_passing: list[str]
    newly_failing: list[str]

    @property
    def regressed(self) -> bool:
        return bool(self.newly_failing) or any(d < 0 for d in self.criterion_deltas.values())


def compare(before: VersionReport, after: VersionReport) -> Comparison:
    b = {g.scenario_id: g.passed for g in before.grades}
    a = {g.scenario_id: g.passed for g in after.grades}
    return Comparison(
        before=before.prompt_version,
        after=after.prompt_version,
        pass_rate_delta=round(after.pass_rate - before.pass_rate, 4),
        criterion_deltas={k: round(after.per_criterion.get(k, 0.0) - v, 4) for k, v in before.per_criterion.items()},
        newly_passing=sorted(s for s in a if a[s] and not b.get(s, False)),
        newly_failing=sorted(s for s in a if not a[s] and b.get(s, False)),
    )


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def format_table(reports: list[VersionReport]) -> str:
    """Render versions side by side: pass rate, score, coverage, forbidden count, per-criterion."""
    if not reports:
        return "(no reports)"
    reports = sorted(reports, key=lambda r: r.prompt_version)
    head = ["metric"] + [r.label for r in reports]
    if len(reports) > 1:
        head.append(f"delta {reports[0].label} to {reports[-1].label}")
    rows: list[list[str]] = []

    def row(name: str, values: list[float], fmt=_pct) -> None:
        cells = [name] + [fmt(v) for v in values]
        if len(values) > 1:
            d = values[-1] - values[0]
            cells.append(("+" if d >= 0 else "") + (fmt(d) if fmt is _pct else str(d)))
        rows.append(cells)

    row("pass rate", [r.pass_rate for r in reports])
    row("mean score", [r.mean_score for r in reports])
    row("required-action coverage", [r.required_action_coverage for r in reports])
    row("forbidden actions", [r.forbidden_violations for r in reports], fmt=lambda v: str(int(v)))
    for crit in reports[0].per_criterion:
        row(f"  {crit}", [r.per_criterion.get(crit, 0.0) for r in reports])

    widths = [max(len(r[i]) for r in [head] + rows) for i in range(len(head))]
    line = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(head)) + " |"
    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    body = ["| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(r)) + " |" for r in rows]
    mode = ", ".join(sorted({r.mode for r in reports}))
    title = f"{reports[0].procedure_slug}: {reports[0].scenarios} scenarios, mode={mode}"
    return "\n".join([title, line, sep, *body])
