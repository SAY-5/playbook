from copy import deepcopy
from pathlib import Path

from playbook.agent.prompt import Correction, PromptSpec
from playbook.agent.store import LocalRunStore
from playbook.config import Settings
from playbook.evals.report import VersionReport
from playbook.feedback.approval import PromotionLog, audit_trail, format_audit, gate
from playbook.feedback.diff import diff_versions, format_diff
from playbook.feedback.loop import run_loop
from playbook.feedback.review import ReviewQueue
from playbook.ingest.models import Citation, Rule, Step
from playbook.runner import Runner, Workspace

SLUG = "support-triage"


def _runner(settings: Settings, procedure_dir: Path) -> Runner:
    ws = Workspace(procedure_dir, settings.runs_dir)
    ws.ingest()
    return Runner(settings, ws)


def _report(version: int, *, forbidden: int = 0) -> VersionReport:
    return VersionReport(
        procedure_slug=SLUG,
        prompt_version=version,
        mode="offline",
        scenarios=16,
        passed=16,
        pass_rate=1.0,
        mean_score=1.0,
        per_criterion={},
        required_action_coverage=1.0,
        forbidden_violations=forbidden,
    )


def _corrections() -> list[Correction]:
    return [
        Correction("create-ticket", 'Set summary to "[{severity}] {title}".', "summary_prefixed", 1, "v1 triage-01"),
        Correction("create-ticket", 'When severity is sev1, set priority to "Highest".', "priority", 1, "v1 triage-01"),
        Correction(
            "escalate", "When tier is enterprise, post to #support-escalations.", "escalated", 1, "v1 triage-05"
        ),
        Correction(
            "escalate", "When posting to Slack, do not include the customer email.", "no_pii", 1, "v1 triage-03"
        ),
    ]


def test_forbidden_actions_block_promotion(settings: Settings, triage_dir: Path):
    runner = _runner(settings, triage_dir)
    result = run_loop(runner, runner.ws.prompt(), max_rounds=4)
    first, last = result.reports[0], result.reports[-1]
    assert first.forbidden_violations > 0
    log = PromotionLog(runner.store, runner.procedure.slug)

    blocked = log.decide(first, [], "dana")
    assert blocked.decision == "blocked" and not blocked.promoted
    assert any(b.startswith("forbidden-action") for b in blocked.blockers)
    assert "no_pii_in_slack" in " ".join(blocked.blockers)
    assert log.current() is None

    assert last.forbidden_violations == 0
    queue = ReviewQueue(runner.store, runner.procedure.slug)
    promoted = log.decide(last, queue.pending(last.prompt_version), "dana", note="leaks cleared")
    assert promoted.promoted and promoted.blockers == []
    assert log.current() == last.prompt_version
    assert [p.decision for p in log.all()] == ["blocked", "promoted"]


def test_pending_proposals_block_promotion(tmp_path: Path):
    queue = ReviewQueue(LocalRunStore(tmp_path), SLUG)
    pending = queue.propose(_corrections()[:2], 1)
    blockers = gate(_report(2), pending)
    assert [b.kind for b in blockers] == ["pending-review"]
    assert "p1-01, p1-02" in blockers[0].detail
    assert gate(_report(2), []) == []


def test_diff_reports_added_removed_and_changed_steps(settings: Settings, triage_dir: Path):
    runner = _runner(settings, triage_dir)
    proc = runner.procedure
    v1 = PromptSpec(procedure_slug=proc.slug)
    v2 = v1.with_corrections(_corrections()[:1], notes="reviewed")

    after_proc = deepcopy(proc)
    dropped = after_proc.steps.pop(2)
    after_proc.steps[0].title = "Read the request carefully"
    after_proc.steps.append(
        Step(
            id="hand-over",
            index=6,
            title="Hand over",
            instruction="Tell the requester what happened.",
            tool="slack.post",
            citation=Citation("sop.md", 90),
            rules=[Rule("Post the ticket key back to the requester.", Citation("sop.md", 91))],
        )
    )

    diff = diff_versions(proc, v1, v2, after_proc=after_proc)
    assert [s.id for s in diff.added] == ["hand-over"]
    assert [s.id for s in diff.removed] == [dropped.id]
    changed = {c.step_id: c for c in diff.changed}
    assert changed["create-ticket"].added == ('Set summary to "[{severity}] {title}".',)
    assert changed["create-ticket"].removed == ()
    assert changed[proc.steps[0].id].retitled == (proc.steps[0].title, "Read the request carefully")
    assert dropped.id not in diff.unchanged and "create-ticket" not in diff.unchanged
    assert not diff.identical

    text = format_diff(diff)
    assert "1 step(s) added, 1 removed, 2 changed" in text
    assert "added   6. Hand over [hand-over]" in text
    assert '+ Set summary to "[{severity}] {title}".' in text
    assert diff_versions(proc, v1, v1).identical


def test_audit_trail_records_every_decision(tmp_path: Path):
    store = LocalRunStore(tmp_path)
    queue = ReviewQueue(store, SLUG)
    proposals = queue.propose(_corrections(), 1)
    assert [p.id for p in proposals] == ["p1-01", "p1-02", "p1-03", "p1-04"]

    queue.approve("p1-01", "dana", note="matches the priority matrix")
    edited = queue.approve("p1-02", "raj", text='When severity is sev1, set priority to "Highest" immediately.')
    queue.reject("p1-03", "dana", note="the SOP already covers enterprise")
    assert edited.edited and edited.final_text.endswith('"Highest" immediately.')

    log = PromotionLog(store, SLUG)
    assert log.decide(_report(2), queue.pending(1), "dana").decision == "blocked"
    queue.approve("p1-04", "raj")
    queue.mark_applied(queue.approved(1), 2)
    assert log.decide(_report(2), queue.pending(1), "dana", note="signed off").promoted

    entries = audit_trail(queue.all(), log.all())
    assert [e.action for e in entries] == ["approved", "edited", "rejected", "approved", "blocked", "promoted"]
    assert [e.subject for e in entries] == ["p1-01", "p1-02", "p1-03", "p1-04", "v2", "v2"]
    assert [e.actor for e in entries] == ["dana", "raj", "dana", "raj", "dana", "dana"]
    assert "applied in v2" in entries[1].detail and "Highest" in entries[1].detail
    assert "the SOP already covers enterprise" in entries[2].detail
    assert "pending-review" in entries[4].detail and "signed off" in entries[5].detail

    text = format_audit(SLUG, entries)
    assert "6 decision(s) by dana, raj" in text
    assert format_audit(SLUG, []).endswith("no review decisions recorded")
