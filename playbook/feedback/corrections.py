"""Derive explicit prompt corrections from graded failures.

For each failed criterion that carries a remediation, the failing scenarios are grouped and the
smallest set of scenario facts that separates them from scenarios with a different expectation is
turned into a condition, for example `severity is sev2 and tier is enterprise`.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any

from playbook.agent.prompt import Correction
from playbook.evals.grader import CriterionResult, RunGrade
from playbook.evals.rubric import Criterion, Rubric
from playbook.evals.scenarios import Scenario, ScenarioSet


def cond_text(var: str, value: Any) -> str:
    if var == "customer_facing":
        truthy = str(value).lower() in ("yes", "true", "1")
        return "the incident is customer-facing" if truthy else "the incident is not customer-facing"
    if var == "kb_hit":
        return "a KB match is found" if value else "no KB match is found"
    return f"{var} is {value}"


def _fill(rule: str, cond: str, values: dict[str, Any]) -> str:
    text = rule
    if cond:
        text = text.replace("<cond>", cond)
    else:
        text = re.sub(r"^When <cond>, (\w)", lambda m: m.group(1).upper(), text)
        text = text.replace(" when <cond>", "").replace("<cond>", "")
    for k, v in values.items():
        text = text.replace(f"<{k}>", str(v))
    return text


def _discriminate(
    target: Scenario,
    target_expected: Any,
    others: list[tuple[Scenario, Any]],
    cond_vars: list[str],
) -> str:
    """Smallest subset of cond_vars whose values on `target` never coincide with a scenario that
    expects something different. Falls back to all vars."""
    if not cond_vars:
        return ""
    for size in range(1, len(cond_vars) + 1):
        for subset in combinations(cond_vars, size):
            mine = tuple(target.facts.get(v) for v in subset)
            clash = any(tuple(o.facts.get(v) for v in subset) == mine and exp != target_expected for o, exp in others)
            if not clash:
                return " and ".join(cond_text(v, target.facts.get(v)) for v in subset)
    return " and ".join(cond_text(v, target.facts.get(v)) for v in cond_vars)


def derive_corrections(
    grades: list[RunGrade], scenarios: ScenarioSet, rubric: Rubric, version: int
) -> list[Correction]:
    out: list[Correction] = []
    seen: set[tuple[str, str]] = set()
    for crit in rubric.criteria:
        rem = crit.remediation
        if rem is None:
            continue
        rows: list[tuple[Scenario, CriterionResult]] = []
        for g in grades:
            res = next((r for r in g.results if r.id == crit.id), None)
            if res is not None:
                rows.append((scenarios.get(g.scenario_id), res))
        failures = [
            (sc, res)
            for sc, res in rows
            if not res.passed
            and (rem.only_when_expected is None or res.evidence.get("expected") == rem.only_when_expected)
        ]
        if not failures:
            continue
        others = [(sc, res.evidence.get("expected")) for sc, res in rows]
        placeholders = [p for p in re.findall(r"<(\w+)>", rem.rule) if p != "cond"]
        for sc, res in failures:
            values = {p: res.evidence.get(p) for p in placeholders if p in res.evidence}
            cond = _discriminate(sc, res.evidence.get("expected"), others, rem.cond_vars)
            text = _fill(rem.rule, cond, values)
            if (rem.step, text) in seen:
                continue
            seen.add((rem.step, text))
            supporting = [
                s.id
                for s, r in failures
                if _fill(
                    rem.rule,
                    _discriminate(s, r.evidence.get("expected"), others, rem.cond_vars),
                    {p: r.evidence.get(p) for p in placeholders if p in r.evidence},
                )
                == text
            ]
            out.append(
                Correction(
                    step_id=rem.step,
                    text=text,
                    criterion=crit.id,
                    version=version + 1,
                    evidence=f"failed in v{version} on {', '.join(supporting[:4])}"
                    + (f" and {len(supporting) - 4} more" if len(supporting) > 4 else ""),
                )
            )
    return out


def describe(criterion: Criterion, correction: Correction) -> str:
    return f"[{correction.step_id}] {correction.text}  ({criterion.id}; {correction.evidence})"
