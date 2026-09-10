"""Promotion of a prompt version, its gate, and the audit trail behind both.

Deriving a correction and approving it are separate acts, and so are approving corrections and
declaring the resulting version fit to use. Promotion is the second act: a reviewer signs off on a
graded version, and the gate refuses while the version still commits a forbidden action or while
proposals from it are unreviewed. Every attempt, allowed or refused, is written to the run store
next to the proposals it draws on, so the trail says who approved what and when.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from playbook.agent.store import RunStore
from playbook.evals.report import VersionReport
from playbook.feedback.review import Proposal

KIND = "promotions"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Blocker:
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.detail}"


@dataclass
class Promotion:
    id: str
    procedure_slug: str
    version: int
    decision: str
    reviewer: str
    at: str = field(default_factory=_now)
    note: str = ""
    blockers: list[str] = field(default_factory=list)
    pass_rate: float = 0.0
    forbidden_violations: int = 0

    @property
    def promoted(self) -> bool:
        return self.decision == "promoted"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Promotion:
        return cls(**d)


def gate(report: VersionReport, pending: list[Proposal]) -> list[Blocker]:
    """Everything standing between this graded version and promotion."""
    blockers: list[Blocker] = []
    offences: dict[str, list[str]] = {}
    for g in report.grades:
        for r in g.results:
            if r.forbidden and not r.passed:
                offences.setdefault(r.id, []).append(g.scenario_id)
    for criterion, scenarios in sorted(offences.items()):
        shown = ", ".join(scenarios[:4]) + (f" +{len(scenarios) - 4}" if len(scenarios) > 4 else "")
        blockers.append(Blocker("forbidden-action", f"{criterion} in {len(scenarios)} scenario(s): {shown}"))
    if pending:
        ids = ", ".join(p.id for p in pending)
        blockers.append(Blocker("pending-review", f"{len(pending)} proposal(s) awaiting a decision: {ids}"))
    return blockers


class PromotionLog:
    """The promotion decisions recorded for one procedure, backed by the run store."""

    def __init__(self, store: RunStore, procedure_slug: str):
        self.store = store
        self.slug = procedure_slug

    def all(self) -> list[Promotion]:
        items = [Promotion.from_dict(d) for d in self.store.list_records(KIND, self.slug)]
        return sorted(items, key=lambda p: (p.at, p.id))

    def current(self) -> int | None:
        """The highest version that was promoted and not superseded by a later block."""
        promoted = [p.version for p in self.all() if p.promoted]
        return max(promoted) if promoted else None

    def decide(self, report: VersionReport, pending: list[Proposal], reviewer: str, note: str = "") -> Promotion:
        """Run the gate and record the outcome. A blocked version is recorded, never promoted."""
        blockers = gate(report, pending)
        seq = sum(1 for p in self.all() if p.version == report.prompt_version) + 1
        promotion = Promotion(
            id=f"d{report.prompt_version}-{seq:02d}",
            procedure_slug=self.slug,
            version=report.prompt_version,
            decision="blocked" if blockers else "promoted",
            reviewer=reviewer,
            note=note,
            blockers=[str(b) for b in blockers],
            pass_rate=report.pass_rate,
            forbidden_violations=report.forbidden_violations,
        )
        self.store.save_record(KIND, self.slug, promotion.id, promotion.to_dict())
        return promotion


@dataclass(frozen=True)
class AuditEntry:
    at: str
    actor: str
    action: str
    subject: str
    detail: str


def audit_trail(proposals: list[Proposal], promotions: list[Promotion]) -> list[AuditEntry]:
    """Every reviewer act on one procedure, oldest first: correction decisions and version decisions."""
    entries: list[AuditEntry] = []
    for p in proposals:
        if not p.decided_at:
            continue
        action = "edited" if p.status == "approved" and p.edited else p.status
        detail = f"[{p.step_id}] {p.final_text}"
        if p.applied_in is not None:
            detail += f" (applied in v{p.applied_in})"
        if p.note:
            detail += f" note: {p.note}"
        entries.append(AuditEntry(p.decided_at, p.reviewer, action, p.id, detail))
    for pr in promotions:
        detail = "; ".join(pr.blockers) if pr.blockers else f"pass rate {pr.pass_rate:.0%}"
        if pr.note:
            detail += f" note: {pr.note}"
        entries.append(AuditEntry(pr.at, pr.reviewer, pr.decision, f"v{pr.version}", detail))
    return sorted(entries, key=lambda e: (e.at, e.subject))


def format_promotion(promotion: Promotion) -> str:
    head = f"v{promotion.version} {promotion.decision} by {promotion.reviewer} at {promotion.at}"
    if not promotion.blockers:
        return f"{head} (pass rate {promotion.pass_rate:.0%}, {promotion.forbidden_violations} forbidden action(s))"
    return "\n".join([head] + [f"  blocked by {b}" for b in promotion.blockers])


def format_audit(procedure_slug: str, entries: list[AuditEntry]) -> str:
    if not entries:
        return f"{procedure_slug}: no review decisions recorded"
    actors = sorted({e.actor for e in entries if e.actor})
    lines = [f"{procedure_slug} audit trail: {len(entries)} decision(s) by {', '.join(actors)}"]
    lines.extend(f"  {e.at}  {e.actor:<10s} {e.action:<9s} {e.subject:<8s} {e.detail}" for e in entries)
    return "\n".join(lines)
