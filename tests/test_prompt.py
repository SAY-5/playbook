from pathlib import Path

from playbook.agent.prompt import Correction, PromptSpec
from playbook.ingest import ingest_procedure


def test_render_includes_steps_decisions_and_prohibitions(triage_dir: Path):
    proc = ingest_procedure(triage_dir)
    text = PromptSpec(procedure_slug=proc.slug).render(proc)
    assert '"Support triage" (prompt v1)' in text
    assert "### Step 2: Create the ticket [create-ticket] (tool: jira.create_issue)" in text
    assert "## Decision points (from the walkthrough)" in text
    assert "(walkthrough.md:7)" in text
    assert "- Never transition a ticket to Done during triage." in text
    assert "Corrections:" not in text


def test_versioning_appends_corrections_under_the_step_and_dedups(triage_dir: Path, tmp_path: Path):
    proc = ingest_procedure(triage_dir)
    v1 = PromptSpec(procedure_slug=proc.slug)
    fix = Correction("create-ticket", 'When severity is sev1, set priority to "Highest".', "priority", 1)
    v2 = v1.with_corrections([fix], notes="test")
    assert (v2.version, v2.parent_version) == (2, 1)
    assert v2.corrections[0].version == 2
    rendered = v2.render(proc)
    step_block = rendered.split("### Step 2:")[1].split("### Step 3:")[0]
    assert 'Corrections:\n- (v2) When severity is sev1, set priority to "Highest".' in step_block
    v3 = v2.with_corrections([fix, Correction("escalate", "When tier is enterprise, post to #support-escalations mentioning the issue key.", "esc", 2)], notes="again")
    assert len(v3.corrections) == 2
    assert [c.version for c in v3.corrections] == [2, 3]
    assert v1.corrections == []

    prompts = tmp_path / "prompts"
    for spec in (v1, v2, v3):
        spec.save(prompts)
    assert PromptSpec.latest(prompts).version == 3
    assert PromptSpec.load(prompts, 2).corrections == v2.corrections
    assert PromptSpec.latest(tmp_path / "missing") is None
