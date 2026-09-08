"""Structured representation of an expert procedure with citations to the source text."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Citation:
    source: str
    line: int

    def __str__(self) -> str:
        return f"{self.source}:{self.line}"


@dataclass
class Rule:
    """A single instruction line attached to a step, section or decision."""

    text: str
    citation: Citation


@dataclass
class Step:
    id: str
    index: int
    title: str
    instruction: str
    tool: str | None
    citation: Citation
    rules: list[Rule] = field(default_factory=list)


@dataclass
class DecisionPoint:
    """A conditional the expert stated, linked to the step it influences when we can tell."""

    id: str
    text: str
    citation: Citation
    step_id: str | None = None
    kind: str = "decision"


@dataclass
class Procedure:
    name: str
    slug: str
    purpose: str
    preconditions: list[Rule] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    decision_points: list[DecisionPoint] = field(default_factory=list)
    escalation_rules: list[Rule] = field(default_factory=list)
    forbidden: list[Rule] = field(default_factory=list)
    checks: list[Rule] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def step(self, step_id: str) -> Step:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(step_id)

    @property
    def required_tools(self) -> list[str]:
        return [s.tool for s in self.steps if s.tool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Procedure:
        def cite(d: dict[str, Any]) -> Citation:
            return Citation(**d)

        def rules(items: list[dict[str, Any]]) -> list[Rule]:
            return [Rule(text=r["text"], citation=cite(r["citation"])) for r in items]

        steps = [
            Step(
                id=s["id"],
                index=s["index"],
                title=s["title"],
                instruction=s["instruction"],
                tool=s.get("tool"),
                citation=cite(s["citation"]),
                rules=rules(s.get("rules", [])),
            )
            for s in data["steps"]
        ]
        decisions = [
            DecisionPoint(
                id=d["id"],
                text=d["text"],
                citation=cite(d["citation"]),
                step_id=d.get("step_id"),
                kind=d.get("kind", "decision"),
            )
            for d in data.get("decision_points", [])
        ]
        return cls(
            name=data["name"],
            slug=data["slug"],
            purpose=data.get("purpose", ""),
            preconditions=rules(data.get("preconditions", [])),
            steps=steps,
            decision_points=decisions,
            escalation_rules=rules(data.get("escalation_rules", [])),
            forbidden=rules(data.get("forbidden", [])),
            checks=rules(data.get("checks", [])),
            sources=list(data.get("sources", [])),
        )
