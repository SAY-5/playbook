"""Versioned system prompts built from a Procedure plus accumulated corrections."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playbook.ingest.models import Procedure


@dataclass(frozen=True)
class Correction:
    """An explicit rule appended to one SOP step, produced by the feedback loop."""

    step_id: str
    text: str
    criterion: str
    version: int
    evidence: str = ""
    proposal_id: str = ""


@dataclass
class PromptSpec:
    procedure_slug: str
    version: int = 1
    parent_version: int | None = None
    corrections: list[Correction] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    notes: str = "initial prompt built from the ingested procedure"

    @property
    def label(self) -> str:
        return f"v{self.version}"

    def with_corrections(self, new: list[Correction], notes: str) -> PromptSpec:
        """Create the next version. Existing corrections are kept; duplicates are dropped."""
        seen = {(c.step_id, c.text) for c in self.corrections}
        merged = list(self.corrections)
        for c in new:
            if (c.step_id, c.text) not in seen:
                merged.append(Correction(c.step_id, c.text, c.criterion, self.version + 1, c.evidence, c.proposal_id))
                seen.add((c.step_id, c.text))
        return PromptSpec(
            procedure_slug=self.procedure_slug,
            version=self.version + 1,
            parent_version=self.version,
            corrections=merged,
            notes=notes,
        )

    def render(self, proc: Procedure) -> str:
        by_step: dict[str, list[Correction]] = {}
        for c in self.corrections:
            by_step.setdefault(c.step_id, []).append(c)

        out: list[str] = [
            f'You are an operations agent executing the procedure "{proc.name}" (prompt {self.label}).',
            proc.purpose,
            "Work through the steps in order, calling one tool at a time and using only the tools "
            "provided. Read each tool result before the next call. When every step is done, reply "
            "with a one-line summary and stop.",
            "",
        ]
        if proc.preconditions:
            out.append("## Preconditions")
            out.extend(f"- {r.text}" for r in proc.preconditions)
            out.append("")
        out.append("## Steps")
        for step in proc.steps:
            tool = f" (tool: {step.tool})" if step.tool else ""
            out.append(f"### Step {step.index}: {step.title} [{step.id}]{tool}")
            if step.instruction:
                out.append(step.instruction)
            out.extend(f"- {r.text}" for r in step.rules)
            fixes = by_step.get(step.id, [])
            if fixes:
                out.append("Corrections:")
                out.extend(f"- (v{c.version}) {c.text}" for c in fixes)
            out.append("")
        decisions = [d for d in proc.decision_points if d.kind == "decision"]
        if decisions:
            out.append("## Decision points (from the walkthrough)")
            for d in decisions:
                tag = f"[{d.step_id}] " if d.step_id else ""
                out.append(f"- {tag}{d.text} ({d.citation})")
            out.append("")
        if proc.escalation_rules:
            out.append("## Escalation")
            out.extend(f"- {r.text}" for r in proc.escalation_rules)
            out.append("")
        forbidden = [r.text for r in proc.forbidden] + [d.text for d in proc.decision_points if d.kind == "forbidden"]
        if forbidden:
            out.append("## Never")
            out.extend(f"- {t}" for t in dict.fromkeys(forbidden))
            out.append("")
        if proc.checks:
            out.append("## Checks before finishing")
            out.extend(f"- {r.text}" for r in proc.checks)
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptSpec:
        return cls(
            procedure_slug=data["procedure_slug"],
            version=data["version"],
            parent_version=data.get("parent_version"),
            corrections=[Correction(**c) for c in data.get("corrections", [])],
            created_at=data.get("created_at", ""),
            notes=data.get("notes", ""),
        )

    def save(self, prompts_dir: Path) -> Path:
        prompts_dir.mkdir(parents=True, exist_ok=True)
        path = prompts_dir / f"{self.label}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return path

    @classmethod
    def load(cls, prompts_dir: Path, version: int | str) -> PromptSpec:
        label = version if isinstance(version, str) else f"v{version}"
        return cls.from_dict(json.loads((prompts_dir / f"{label}.json").read_text()))

    @classmethod
    def latest(cls, prompts_dir: Path) -> PromptSpec | None:
        versions = sorted(
            (int(p.stem[1:]) for p in prompts_dir.glob("v*.json") if p.stem[1:].isdigit()),
            reverse=True,
        )
        return cls.load(prompts_dir, versions[0]) if versions else None
