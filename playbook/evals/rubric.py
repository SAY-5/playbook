"""Expert rubric schema loaded from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CRITERION_KINDS = {
    "tool_called",
    "tool_order",
    "issue_field",
    "slack_post",
    "transition",
    "forbidden_transition",
    "forbidden_channel",
    "no_pii_in_slack",
    "text_absent",
    "judge",
}


@dataclass
class Remediation:
    """How to turn a failure of this criterion into a prompt correction.

    `rule` may contain `<cond>` (filled with the discriminating condition derived from the failing
    scenarios), `<expected>` (the expected value) and any `<name>` present in the grader's evidence.
    """

    step: str
    rule: str
    cond_vars: list[str] = field(default_factory=list)
    only_when_expected: Any = None


@dataclass
class Criterion:
    id: str
    kind: str
    description: str
    weight: float = 1.0
    forbidden: bool = False
    params: dict[str, Any] = field(default_factory=dict)
    remediation: Remediation | None = None


@dataclass
class Rubric:
    procedure_slug: str
    pass_threshold: float
    criteria: list[Criterion]

    @classmethod
    def load(cls, path: Path) -> Rubric:
        data = yaml.safe_load(path.read_text())
        criteria = []
        for c in data["criteria"]:
            if c["kind"] not in CRITERION_KINDS:
                raise ValueError(f"{path}: unknown criterion kind {c['kind']!r} in {c['id']}")
            rem = c.get("remediation")
            criteria.append(
                Criterion(
                    id=c["id"],
                    kind=c["kind"],
                    description=c.get("description", ""),
                    weight=float(c.get("weight", 1.0)),
                    forbidden=bool(c.get("forbidden", False)),
                    params=dict(c.get("params", {})),
                    remediation=Remediation(
                        step=rem["step"],
                        rule=rem["rule"],
                        cond_vars=list(rem.get("cond_vars", [])),
                        only_when_expected=rem.get("only_when_expected"),
                    )
                    if rem
                    else None,
                )
            )
        ids = [c.id for c in criteria]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{path}: duplicate criterion ids")
        return cls(
            procedure_slug=data["procedure"],
            pass_threshold=float(data.get("pass_threshold", 1.0)),
            criteria=criteria,
        )

    @property
    def required_actions(self) -> list[str]:
        return [c.params["tool"] for c in self.criteria if c.kind == "tool_called"]

    def criterion(self, criterion_id: str) -> Criterion:
        for c in self.criteria:
            if c.id == criterion_id:
                return c
        raise KeyError(criterion_id)
