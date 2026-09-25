"""A tagged bank of every scenario a procedure has been run on, and how each version scored it.

Scenario sets get edited: a branch is synthesized, a case is retired, an incident becomes a test.
The bank keeps them all with their tags and their per-version outcomes, so a later version can be
replayed against the whole history rather than against whatever `scenarios.yaml` happens to hold.
The run store persists it as `<slug>/bank.json`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from playbook.evals.scenarios import Scenario, ScenarioSet


@dataclass
class BankEntry:
    scenario: Scenario
    added_from: str = "scenarios.yaml"
    outcomes: dict[int, bool] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.scenario.id

    @property
    def tags(self) -> tuple[str, ...]:
        return tuple(self.scenario.tags)

    @property
    def ever_failed(self) -> bool:
        return any(not passed for passed in self.outcomes.values())

    @property
    def untried(self) -> bool:
        return not self.outcomes

    def outcome_before(self, version: int) -> tuple[int, bool] | None:
        """The most recent recorded outcome from a version earlier than `version`."""
        earlier = [v for v in self.outcomes if v < version]
        return (max(earlier), self.outcomes[max(earlier)]) if earlier else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.to_dict(),
            "added_from": self.added_from,
            "outcomes": {str(v): p for v, p in sorted(self.outcomes.items())},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BankEntry:
        s = d["scenario"]
        return cls(
            scenario=Scenario(id=s["id"], intake=s["intake"], expected=s.get("expected", {}), tags=s.get("tags", [])),
            added_from=d.get("added_from", ""),
            outcomes={int(v): bool(p) for v, p in d.get("outcomes", {}).items()},
        )


@dataclass
class ScenarioBank:
    procedure_slug: str
    entries: list[BankEntry] = field(default_factory=list)

    def get(self, scenario_id: str) -> BankEntry:
        for e in self.entries:
            if e.id == scenario_id:
                return e
        raise KeyError(scenario_id)

    @property
    def tags(self) -> list[str]:
        return sorted({t for e in self.entries for t in e.tags})

    def by_tag(self, tag: str) -> list[BankEntry]:
        return [e for e in self.entries if tag in e.tags]

    def historical_failures(self) -> list[BankEntry]:
        return [e for e in self.entries if e.ever_failed]

    def select(self, *, tag: str | None = None, failures_only: bool = False) -> list[BankEntry]:
        chosen = self.by_tag(tag) if tag else list(self.entries)
        if failures_only:
            chosen = [e for e in chosen if e.ever_failed or e.untried]
        return chosen

    def add(self, scenarios: ScenarioSet, source: str = "scenarios.yaml") -> list[str]:
        """Merge a scenario set in. Known ids keep their history and take the newer wording."""
        added: list[str] = []
        known = {e.id: e for e in self.entries}
        for s in scenarios.scenarios:
            if s.id in known:
                known[s.id].scenario = s
                continue
            self.entries.append(BankEntry(scenario=s, added_from=source))
            added.append(s.id)
        return added

    def record(self, version: int, results: Mapping[str, bool]) -> int:
        """Record one version's per-scenario outcomes; scenarios outside the bank are ignored."""
        known = {e.id: e for e in self.entries}
        recorded = 0
        for scenario_id, passed in results.items():
            if scenario_id in known:
                known[scenario_id].outcomes[version] = bool(passed)
                recorded += 1
        return recorded

    def scenario_set(self, entries: list[BankEntry] | None = None) -> ScenarioSet:
        chosen = self.entries if entries is None else entries
        return ScenarioSet(procedure_slug=self.procedure_slug, scenarios=[e.scenario for e in chosen])

    def to_dict(self) -> dict[str, Any]:
        return {"procedure": self.procedure_slug, "entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenarioBank:
        return cls(procedure_slug=data["procedure"], entries=[BankEntry.from_dict(e) for e in data["entries"]])


def format_bank(bank: ScenarioBank) -> str:
    versions = sorted({v for e in bank.entries for v in e.outcomes})
    failures = bank.historical_failures()
    lines = [
        f"{bank.procedure_slug} bank: {len(bank.entries)} scenario(s), {len(bank.tags)} tag(s), "
        f"versions {', '.join(f'v{v}' for v in versions) or 'none'}, "
        f"{len(failures)} with a recorded failure"
    ]
    for tag in bank.tags:
        entries = bank.by_tag(tag)
        failed = sum(1 for e in entries if e.ever_failed)
        lines.append(f"  {tag:<16s} {len(entries):>2d} scenario(s), {failed} with a recorded failure")
    if failures:
        lines.append("historical failures: " + ", ".join(e.id for e in failures))
    return "\n".join(lines)
