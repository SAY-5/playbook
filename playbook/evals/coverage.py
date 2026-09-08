"""Decision-branch and rubric coverage of a scenario set.

Every walkthrough decision point is split into the branches an expert would test: each severity,
tier or impact level it names, both sides of a KB match or customer-facing condition, and one
`otherwise` branch when the decision names only some of a variable's values. A scenario covers a
branch when its facts take the branch's values. Rubric coverage counts how many scenarios exercise
each criterion and, for criteria keyed on an expected outcome, how many sit on each side.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from itertools import product
from typing import Any

from playbook.evals.rubric import Criterion, Rubric
from playbook.evals.scenarios import Scenario, ScenarioSet
from playbook.ingest.models import DecisionPoint, Procedure

_SEV = re.compile(r"\bsev[1-4]\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")

# Enumerated variables a decision can branch on, in the order an `otherwise` branch falls back to.
VARIABLES: dict[str, list[Any]] = {
    "severity": ["sev1", "sev2", "sev3", "sev4"],
    "tier": ["enterprise", "pro", "free"],
    "impact": ["full outage", "partial outage", "degraded", "internal"],
    "kb_hit": [True, False],
    "customer_facing": [True, False],
}


def norm(var: str, value: Any) -> Any:
    """Normalise a scenario fact so it compares with a branch value."""
    if var in ("kb_hit", "customer_facing"):
        return value if isinstance(value, bool) else str(value).strip().lower() in ("yes", "true", "1")
    return None if value is None else str(value).strip().lower()


def branch_values(text: str) -> dict[str, list[Any]]:
    """The variable values a decision sentence names, keyed by variable."""
    low = text.lower()
    found: dict[str, list[Any]] = {}
    sevs = list(dict.fromkeys(m.lower() for m in _SEV.findall(text)))
    if sevs:
        found["severity"] = sevs
    tiers = [t for t in VARIABLES["tier"] if re.search(rf"\b{t}\b", low)]
    if tiers:
        found["tier"] = tiers
    impacts = [i for i in VARIABLES["impact"] if i in low]
    if impacts:
        found["impact"] = impacts
    if "kb" in low or "knowledge base" in low:
        found["kb_hit"] = [True, False]
    if "customer-facing" in low or "customer facing" in low:
        found["customer_facing"] = [True, False]
    return found


@dataclass
class Branch:
    decision_id: str
    label: str
    facts: dict[str, Any]
    otherwise: bool = False
    excludes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def id(self) -> str:
        tail = "otherwise" if self.otherwise else "+".join(f"{k}={v}" for k, v in self.facts.items())
        return f"{self.decision_id}/{tail}"

    def covered_by(self, scenario: Scenario) -> bool:
        facts = scenario.facts
        if self.otherwise:
            return not any(_matches(facts, ex) for ex in self.excludes)
        return _matches(facts, self.facts)


def _matches(facts: dict[str, Any], wanted: dict[str, Any]) -> bool:
    return all(norm(k, facts.get(k)) == norm(k, v) for k, v in wanted.items())


def _label(facts: dict[str, Any]) -> str:
    return " and ".join(f"{k}={str(v).lower()}" for k, v in facts.items())


def branches_of(decision: DecisionPoint) -> list[Branch]:
    values = branch_values(decision.text)
    if not values:
        return []
    names = list(values)
    out = [
        Branch(decision.id, _label(dict(zip(names, combo, strict=True))), dict(zip(names, combo, strict=True)))
        for combo in product(*(values[n] for n in names))
    ]
    rest = {n: [v for v in VARIABLES[n] if v not in values[n]] for n in names}
    if any(rest.values()):
        fallback = {n: (rest[n] or values[n])[0] for n in names}
        out.append(
            Branch(
                decision.id,
                f"otherwise ({_label(fallback)})",
                fallback,
                otherwise=True,
                excludes=[b.facts for b in out],
            )
        )
    return out


def extract_branches(proc: Procedure) -> list[Branch]:
    out: list[Branch] = []
    for d in proc.decision_points:
        if d.kind == "decision":
            out.extend(branches_of(d))
    return out


@dataclass
class DecisionCoverage:
    decision_id: str
    text: str
    citation: str
    step_id: str | None
    branches: list[dict[str, Any]]  # {id, label, scenarios: [ids]}

    @property
    def uncovered(self) -> list[dict[str, Any]]:
        return [b for b in self.branches if not b["scenarios"]]


@dataclass
class CriterionCoverage:
    id: str
    kind: str
    scenarios: int
    sides: dict[str, int] = field(default_factory=dict)
    gap: str | None = None


@dataclass
class CoverageReport:
    procedure_slug: str
    scenarios: int
    decisions: list[DecisionCoverage]
    criteria: list[CriterionCoverage]
    unbranched: list[str] = field(default_factory=list)

    @property
    def branches_total(self) -> int:
        return sum(len(d.branches) for d in self.decisions)

    @property
    def branches_covered(self) -> int:
        return sum(1 for d in self.decisions for b in d.branches if b["scenarios"])

    @property
    def uncovered_branches(self) -> list[tuple[DecisionCoverage, dict[str, Any]]]:
        return [(d, b) for d in self.decisions for b in d.uncovered]

    @property
    def criterion_gaps(self) -> list[CriterionCoverage]:
        return [c for c in self.criteria if c.gap]

    @property
    def flagged(self) -> bool:
        return bool(self.uncovered_branches or self.criterion_gaps)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(
            branches_total=self.branches_total,
            branches_covered=self.branches_covered,
            flagged=self.flagged,
        )
        return d


def _criterion_coverage(crit: Criterion, scenarios: list[Scenario]) -> CriterionCoverage:
    n = len(scenarios)
    when = crit.params.get("when_expected")
    key = crit.params.get("equals_expected")
    if when:
        yes = sum(1 for s in scenarios if bool(s.expected.get(when)))
        sides = {"expected": yes, "not_expected": n - yes}
        gap = None if yes and n - yes else f"no scenario where {when} is {'true' if not yes else 'false'}"
        return CriterionCoverage(crit.id, crit.kind, n, sides, gap)
    if key:
        sides: dict[str, int] = {}
        for s in scenarios:
            if key in s.expected:
                sides[str(s.expected[key])] = sides.get(str(s.expected[key]), 0) + 1
        have = sum(sides.values())
        return CriterionCoverage(crit.id, crit.kind, have, sides, None if have else f"no scenario sets expected.{key}")
    if crit.kind == "no_pii_in_slack":
        pii = sum(
            1 for s in scenarios if any(_EMAIL.search(str(v)) or _PHONE.search(str(v)) for v in s.intake.values())
        )
        sides = {"with_pii": pii, "without_pii": n - pii}
        return CriterionCoverage(crit.id, crit.kind, pii, sides, None if pii else "no scenario carries contact PII")
    return CriterionCoverage(crit.id, crit.kind, n)


def coverage(proc: Procedure, scenarios: ScenarioSet, rubric: Rubric) -> CoverageReport:
    decisions: list[DecisionCoverage] = []
    unbranched: list[str] = []
    for d in proc.decision_points:
        if d.kind != "decision":
            continue
        branches = branches_of(d)
        if not branches:
            unbranched.append(d.id)
            continue
        decisions.append(
            DecisionCoverage(
                decision_id=d.id,
                text=d.text,
                citation=str(d.citation),
                step_id=d.step_id,
                branches=[
                    {"id": b.id, "label": b.label, "scenarios": [s.id for s in scenarios.scenarios if b.covered_by(s)]}
                    for b in branches
                ],
            )
        )
    return CoverageReport(
        procedure_slug=proc.slug,
        scenarios=len(scenarios.scenarios),
        decisions=decisions,
        criteria=[_criterion_coverage(c, scenarios.scenarios) for c in rubric.criteria],
        unbranched=unbranched,
    )


def format_coverage(report: CoverageReport) -> str:
    total, covered = report.branches_total, report.branches_covered
    pct = f"{covered / total * 100:.1f}%" if total else "n/a"
    lines = [
        f"{report.procedure_slug} coverage: {report.scenarios} scenarios, {len(report.decisions)} branching "
        f"decisions, {covered}/{total} branches covered ({pct})"
    ]
    for d in report.decisions:
        lines.append(f"  {d.decision_id} [{d.step_id or '-'}] {d.text} ({d.citation})")
        for b in d.branches:
            mark = "ok  " if b["scenarios"] else "GAP "
            ids = ", ".join(b["scenarios"][:4]) + (f" +{len(b['scenarios']) - 4}" if len(b["scenarios"]) > 4 else "")
            lines.append(f"    {mark}{b['label']:<48s} {ids or '-'}")
    if report.unbranched:
        lines.append(f"  unconditional decisions (no branch variables): {', '.join(report.unbranched)}")
    lines.append("criteria:")
    for c in report.criteria:
        sides = " ".join(f"{k}={v}" for k, v in c.sides.items())
        flag = f"  GAP {c.gap}" if c.gap else ""
        lines.append(f"  {c.id:<38s} {c.scenarios:>3d} scenario(s) {sides}{flag}")
    gaps = len(report.uncovered_branches), len(report.criterion_gaps)
    lines.append(
        f"flagged: {gaps[0]} uncovered branch(es), {gaps[1]} criterion gap(s)" if report.flagged else "flagged: none"
    )
    return "\n".join(lines)
