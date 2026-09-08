"""Expert review of derived corrections.

A correction the feedback loop derives is only a proposal until a reviewer approves it, edits it
or rejects it. Proposals and their decisions live in the run store, so the same audit trail is
available on disk and in S3. Only approved proposals (with the reviewer's edited text when there
is one) are turned into corrections for the next prompt version.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from playbook.agent.prompt import Correction
from playbook.agent.store import RunStore

STATUSES = ("pending", "approved", "rejected")
AUTO_REVIEWER = "auto"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Proposal:
    id: str
    procedure_slug: str
    source_version: int
    step_id: str
    text: str
    criterion: str
    evidence: str
    status: str = "pending"
    applied_text: str | None = None
    reviewer: str = ""
    note: str = ""
    created_at: str = field(default_factory=_now)
    decided_at: str = ""
    applied_in: int | None = None

    @property
    def final_text(self) -> str:
        return self.applied_text if self.applied_text is not None else self.text

    @property
    def edited(self) -> bool:
        return self.applied_text is not None and self.applied_text != self.text

    def to_correction(self) -> Correction:
        return Correction(
            step_id=self.step_id,
            text=self.final_text,
            criterion=self.criterion,
            version=self.source_version + 1,
            evidence=self.evidence,
            proposal_id=self.id,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Proposal:
        return cls(**d)


@dataclass
class ReviewReport:
    procedure_slug: str
    source_version: int
    proposals: list[Proposal]

    def count(self, status: str) -> int:
        return sum(1 for p in self.proposals if p.status == status)

    @property
    def edited(self) -> int:
        return sum(1 for p in self.proposals if p.status == "approved" and p.edited)

    @property
    def applied(self) -> int:
        return sum(1 for p in self.proposals if p.applied_in is not None)

    @property
    def reviewers(self) -> list[str]:
        return sorted({p.reviewer for p in self.proposals if p.reviewer})


class ReviewQueue:
    """Proposals for one procedure, backed by the run store."""

    def __init__(self, store: RunStore, procedure_slug: str):
        self.store = store
        self.slug = procedure_slug

    def all(self, version: int | None = None) -> list[Proposal]:
        items = [Proposal.from_dict(d) for d in self.store.list_proposals(self.slug)]
        return [p for p in items if version is None or p.source_version == version]

    def get(self, proposal_id: str) -> Proposal:
        for p in self.all():
            if p.id == proposal_id:
                return p
        raise KeyError(proposal_id)

    def pending(self, version: int | None = None) -> list[Proposal]:
        return [p for p in self.all(version) if p.status == "pending"]

    def approved(self, version: int, *, unapplied_only: bool = True) -> list[Proposal]:
        return [p for p in self.all(version) if p.status == "approved" and (p.applied_in is None or not unapplied_only)]

    def propose(self, corrections: list[Correction], version: int) -> list[Proposal]:
        """Record corrections derived from version `version` as proposals; duplicates are skipped."""
        existing = {(p.step_id, p.text) for p in self.all(version)}
        count = len(self.all(version))
        added: list[Proposal] = []
        for c in corrections:
            if (c.step_id, c.text) in existing:
                continue
            count += 1
            p = Proposal(
                id=f"p{version}-{count:02d}",
                procedure_slug=self.slug,
                source_version=version,
                step_id=c.step_id,
                text=c.text,
                criterion=c.criterion,
                evidence=c.evidence,
            )
            self.store.save_proposal(self.slug, p.id, p.to_dict())
            existing.add((c.step_id, c.text))
            added.append(p)
        return added

    def decide(
        self, proposal_id: str, status: str, reviewer: str, *, note: str = "", text: str | None = None
    ) -> Proposal:
        if status not in ("approved", "rejected"):
            raise ValueError(f"status must be approved or rejected, not {status!r}")
        p = self.get(proposal_id)
        if p.applied_in is not None:
            raise ValueError(f"{p.id} was already applied in v{p.applied_in}")
        if text is not None and not text.strip():
            raise ValueError("edited text must not be empty")
        p.status = status
        p.reviewer = reviewer
        p.note = note
        p.applied_text = text.strip() if text is not None and status == "approved" else None
        p.decided_at = _now()
        self.store.save_proposal(self.slug, p.id, p.to_dict())
        return p

    def approve(self, proposal_id: str, reviewer: str, *, note: str = "", text: str | None = None) -> Proposal:
        return self.decide(proposal_id, "approved", reviewer, note=note, text=text)

    def reject(self, proposal_id: str, reviewer: str, *, note: str = "") -> Proposal:
        return self.decide(proposal_id, "rejected", reviewer, note=note)

    def approve_pending(self, version: int, reviewer: str = AUTO_REVIEWER, note: str = "") -> list[Proposal]:
        return [self.approve(p.id, reviewer, note=note) for p in self.pending(version)]

    def mark_applied(self, proposals: list[Proposal], new_version: int) -> None:
        for p in proposals:
            p.applied_in = new_version
            self.store.save_proposal(self.slug, p.id, p.to_dict())

    def report(self, version: int) -> ReviewReport:
        return ReviewReport(self.slug, version, self.all(version))


def format_review(report: ReviewReport) -> str:
    head = (
        f"{report.procedure_slug} review of v{report.source_version} corrections: "
        f"{len(report.proposals)} proposed, {report.count('approved')} approved "
        f"({report.edited} edited), {report.count('rejected')} rejected, {report.count('pending')} pending, "
        f"{report.applied} applied"
    )
    lines = [head]
    if report.reviewers:
        lines.append(f"reviewers: {', '.join(report.reviewers)}")
    for p in report.proposals:
        applied = f" -> v{p.applied_in}" if p.applied_in is not None else ""
        who = f" by {p.reviewer}" if p.reviewer else ""
        lines.append(f"  {p.id} {p.status}{who}{applied} [{p.step_id}] {p.text}  ({p.criterion}; {p.evidence})")
        if p.edited:
            lines.append(f"      edited to: {p.applied_text}")
        if p.note:
            lines.append(f"      note: {p.note}")
    return "\n".join(lines)
