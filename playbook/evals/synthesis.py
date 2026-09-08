"""Synthesise eval scenarios from walkthrough decision branches.

Each branch becomes one scenario: the closest hand-written scenario is used as a template, the
branch's values are written into its intake, and expected outcomes are inferred from existing
scenarios that share the values of the criterion's declared condition variables. Outcomes that
no existing scenario can vouch for are left unset and tagged `needs-expert:<key>` so the expert
fills them in before the scenario counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from playbook.evals.coverage import Branch, coverage, extract_branches, norm
from playbook.evals.rubric import Rubric
from playbook.evals.scenarios import Scenario, ScenarioSet
from playbook.ingest.models import Procedure

# Intake facts a branch value is written to. kb_hit is an outcome of the intake text, so a
# template with the same kb_hit is required instead.
_INTAKE_VARS = ("severity", "tier", "impact", "customer_facing")


@dataclass
class Synthesis:
    scenarios: ScenarioSet
    added: list[Scenario] = field(default_factory=list)
    needs_expert: dict[str, list[str]] = field(default_factory=dict)  # scenario id -> expected keys

    @property
    def branches_added(self) -> int:
        return len(self.added)


def _expected_dependencies(rubric: Rubric) -> dict[str, list[str]]:
    """expected key -> the condition variables the rubric says it depends on."""
    deps: dict[str, list[str]] = {}
    for c in rubric.criteria:
        key = c.params.get("equals_expected") or c.params.get("when_expected")
        if key:
            deps.setdefault(key, c.remediation.cond_vars if c.remediation else [])
    return deps


def _template(branch: Branch, existing: list[Scenario]) -> Scenario:
    def score(s: Scenario) -> tuple[int, str]:
        facts = s.facts
        hits = sum(1 for k, v in branch.facts.items() if norm(k, facts.get(k)) == norm(k, v))
        return (hits, s.id)

    return max(existing, key=score)


def _intake_value(var: str, value: object, template: Scenario) -> object:
    if var == "customer_facing":
        return "yes" if value else "no"
    return value


def synthesize_scenario(
    branch: Branch, index: int, existing: list[Scenario], rubric: Rubric
) -> tuple[Scenario, list[str]]:
    template = _template(branch, existing)
    intake = dict(template.intake)
    for var, value in branch.facts.items():
        if var in _INTAKE_VARS and var in intake:
            intake[var] = _intake_value(var, value, template)
    facts = {**{k: v for k, v in intake.items() if k not in ("kind", "report", "title")}}
    facts["kb_hit"] = branch.facts.get("kb_hit", template.expected.get("kb_hit"))
    expected: dict[str, object] = {}
    missing: list[str] = []
    for key, vars_ in _expected_dependencies(rubric).items():
        if key in branch.facts:
            expected[key] = branch.facts[key]
            continue
        witnesses = [
            s for s in existing if key in s.expected and all(norm(v, s.facts.get(v)) == norm(v, facts.get(v)) for v in vars_)
        ]
        if vars_ and witnesses:
            expected[key] = witnesses[0].expected[key]
        elif not vars_ and key in template.expected:
            expected[key] = template.expected[key]
        else:
            missing.append(key)
    if "kb_hit" in template.expected and "kb_hit" not in expected:
        expected["kb_hit"] = facts["kb_hit"]
    tags = ["synthesized", f"from:{branch.decision_id}", f"template:{template.id}"]
    tags += [f"{k}={str(v).lower()}" for k, v in branch.facts.items()]
    tags += [f"needs-expert:{k}" for k in missing]
    return Scenario(id=f"syn-{index:02d}-{branch.decision_id}", intake=intake, expected=expected, tags=tags), missing


def synthesize(
    proc: Procedure, scenarios: ScenarioSet, rubric: Rubric, *, only_uncovered: bool = False
) -> Synthesis:
    """Return the scenario set extended with one scenario per branch (or per uncovered branch)."""
    if not scenarios.scenarios:
        raise ValueError("synthesis needs at least one hand-written scenario as a template")
    branches = extract_branches(proc)
    if only_uncovered:
        report = coverage(proc, scenarios, rubric)
        uncovered = {b["id"] for _, b in report.uncovered_branches}
        branches = [b for b in branches if b.id in uncovered]
    merged = list(scenarios.scenarios)
    result = Synthesis(scenarios=ScenarioSet(scenarios.procedure_slug, merged))
    seen: set[str] = set()
    for branch in branches:
        if branch.id in seen:
            continue
        seen.add(branch.id)
        sc, missing = synthesize_scenario(branch, len(result.added) + 1, scenarios.scenarios, rubric)
        merged.append(sc)
        result.added.append(sc)
        if missing:
            result.needs_expert[sc.id] = missing
    return result
