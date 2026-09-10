"""Step-level diff between two versions of a generated procedure.

A prompt version is the ingested procedure plus the corrections approved so far, so a reviewer
comparing two versions wants the steps side by side: which steps appeared, which disappeared, and
which kept their identity but gained or lost directives.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from playbook.agent.prompt import PromptSpec
from playbook.ingest.models import Procedure


@dataclass(frozen=True)
class StepView:
    """One step of a procedure as a given prompt version states it."""

    id: str
    index: int
    title: str
    tool: str | None
    directives: tuple[str, ...]


@dataclass(frozen=True)
class StepChange:
    """A step present in both versions whose wording, position or directives moved."""

    step_id: str
    title: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    retitled: tuple[str, str] | None = None
    moved: tuple[int, int] | None = None


@dataclass
class ProcedureDiff:
    procedure_slug: str
    before_version: int
    after_version: int
    added: list[StepView] = field(default_factory=list)
    removed: list[StepView] = field(default_factory=list)
    changed: list[StepChange] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return not (self.added or self.removed or self.changed)

    @property
    def summary(self) -> str:
        return (
            f"{self.procedure_slug} v{self.before_version} to v{self.after_version}: "
            f"{len(self.added)} step(s) added, {len(self.removed)} removed, "
            f"{len(self.changed)} changed, {len(self.unchanged)} unchanged"
        )


def step_views(proc: Procedure, spec: PromptSpec) -> list[StepView]:
    """The steps as prompt `spec` renders them: the SOP rules plus the corrections for that step."""
    by_step: dict[str, list[str]] = {}
    for c in spec.corrections:
        by_step.setdefault(c.step_id, []).append(c.text)
    views = []
    for step in proc.steps:
        directives = [r.text for r in step.rules] + by_step.get(step.id, [])
        views.append(
            StepView(id=step.id, index=step.index, title=step.title, tool=step.tool, directives=tuple(directives))
        )
    return views


def diff_steps(
    before: list[StepView], after: list[StepView]
) -> tuple[list[StepView], list[StepView], list[StepChange], list[str]]:
    """Match steps by id and split them into added, removed, changed and unchanged."""
    before_by_id = {s.id: s for s in before}
    after_by_id = {s.id: s for s in after}
    added = [s for s in after if s.id not in before_by_id]
    removed = [s for s in before if s.id not in after_by_id]
    changed: list[StepChange] = []
    unchanged: list[str] = []
    for step_id, new in after_by_id.items():
        old = before_by_id.get(step_id)
        if old is None:
            continue
        gained = tuple(d for d in new.directives if d not in old.directives)
        lost = tuple(d for d in old.directives if d not in new.directives)
        retitled = (old.title, new.title) if old.title != new.title else None
        moved = (old.index, new.index) if old.index != new.index else None
        if gained or lost or retitled or moved:
            changed.append(StepChange(step_id, new.title, gained, lost, retitled, moved))
        else:
            unchanged.append(step_id)
    return added, removed, changed, unchanged


def diff_versions(
    proc: Procedure, before: PromptSpec, after: PromptSpec, *, after_proc: Procedure | None = None
) -> ProcedureDiff:
    """Diff two prompt versions. Pass `after_proc` when the SOP itself was re-ingested between them."""
    added, removed, changed, unchanged = diff_steps(step_views(proc, before), step_views(after_proc or proc, after))
    return ProcedureDiff(
        procedure_slug=proc.slug,
        before_version=before.version,
        after_version=after.version,
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
    )


def format_diff(diff: ProcedureDiff) -> str:
    lines = [diff.summary]
    for s in diff.added:
        lines.append(f"  added   {s.index}. {s.title} [{s.id}] ({len(s.directives)} directive(s))")
        lines.extend(f"    + {d}" for d in s.directives)
    for s in diff.removed:
        lines.append(f"  removed {s.index}. {s.title} [{s.id}] ({len(s.directives)} directive(s))")
        lines.extend(f"    - {d}" for d in s.directives)
    for c in diff.changed:
        lines.append(f"  changed [{c.step_id}] {c.title}")
        if c.retitled:
            lines.append(f"    title: {c.retitled[0]} -> {c.retitled[1]}")
        if c.moved:
            lines.append(f"    position: {c.moved[0]} -> {c.moved[1]}")
        lines.extend(f"    + {d}" for d in c.added)
        lines.extend(f"    - {d}" for d in c.removed)
    if diff.unchanged:
        lines.append(f"  unchanged: {', '.join(diff.unchanged)}")
    return "\n".join(lines)
