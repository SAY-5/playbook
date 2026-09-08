"""Scenario sets: an intake message plus the expert's expected outcome."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Scenario:
    id: str
    intake: dict[str, Any]
    expected: dict[str, Any]
    tags: list[str] = field(default_factory=list)

    @property
    def facts(self) -> dict[str, Any]:
        """Everything a correction condition may refer to."""
        facts = {k: v for k, v in self.intake.items() if k not in ("kind", "report", "title")}
        facts.update({k: v for k, v in self.expected.items() if k in ("kb_hit",)})
        return facts

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "tags": list(self.tags), "intake": dict(self.intake), "expected": dict(self.expected)}

    def render(self) -> str:
        kind = self.intake.get("kind", "request")
        lines = [f"New {kind}"]
        for key, value in self.intake.items():
            if key == "kind":
                continue
            label = key.replace("_", "-").capitalize() if key != "customer_facing" else "Customer-facing"
            lines.append(f"{label}: {value}")
        return "\n".join(lines)


@dataclass
class ScenarioSet:
    procedure_slug: str
    scenarios: list[Scenario]

    @classmethod
    def load(cls, path: Path) -> ScenarioSet:
        data = yaml.safe_load(path.read_text())
        scenarios = [
            Scenario(
                id=s["id"],
                intake=dict(s["intake"]),
                expected=dict(s.get("expected", {})),
                tags=list(s.get("tags", [])),
            )
            for s in data["scenarios"]
        ]
        ids = [s.id for s in scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{path}: duplicate scenario ids")
        return cls(procedure_slug=data["procedure"], scenarios=scenarios)

    def save(self, path: Path, header: str = "") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = yaml.safe_dump(
            {"procedure": self.procedure_slug, "scenarios": [s.to_dict() for s in self.scenarios]},
            sort_keys=False,
            width=120,
        )
        head = "".join(f"# {line}\n" for line in header.splitlines()) if header else ""
        path.write_text(head + body)
        return path

    def get(self, scenario_id: str) -> Scenario:
        for s in self.scenarios:
            if s.id == scenario_id:
                return s
        raise KeyError(scenario_id)
