import json
from pathlib import Path

import pytest

from playbook.ingest import Procedure, ingest_procedure, parse_sop, parse_walkthrough
from playbook.ingest.parser import write_procedure


def test_sop_steps_ids_tools_and_citations(triage_dir: Path):
    proc = parse_sop(triage_dir / "sop.md")
    assert proc.name == "Support triage"
    assert proc.slug == "support-triage"
    assert [s.id for s in proc.steps] == ["kb-search", "create-ticket", "record-findings", "escalate", "set-state"]
    assert proc.required_tools == [
        "kb.search",
        "jira.create_issue",
        "jira.comment",
        "slack.post",
        "jira.transition",
    ]
    create = proc.step("create-ticket")
    assert create.citation.source == "sop.md"
    lines = (triage_dir / "sop.md").read_text().splitlines()
    assert lines[create.citation.line - 1].startswith("2. Create the ticket")
    assert [r.text for r in create.rules][0].startswith("Set priority according to the severity matrix")
    assert "Use project SUP" in create.instruction
    assert len(proc.preconditions) == 2
    assert len(proc.forbidden) == 3
    assert any("Done" in r.text for r in proc.forbidden)


def test_walkthrough_decisions_cite_transcript_lines(triage_dir: Path):
    proc = parse_sop(triage_dir / "sop.md")
    decisions = parse_walkthrough(triage_dir / "walkthrough.md", proc)
    lines = (triage_dir / "walkthrough.md").read_text().splitlines()
    matrix = next(d for d in decisions if "sev1 is Highest" in d.text)
    assert matrix.step_id == "create-ticket"
    assert "[00:41] Expert:" in lines[matrix.citation.line - 1]
    forbidden = [d for d in decisions if d.kind == "forbidden"]
    assert any("email or phone number" in d.text for d in forbidden)
    # interviewer questions never become decisions
    assert not any("Walk me through" in d.text for d in decisions)


def test_ingest_round_trips_through_json(incident_dir: Path, tmp_path: Path):
    proc = ingest_procedure(incident_dir)
    assert proc.sources == ["sop.md", "walkthrough.md"]
    path = write_procedure(proc, tmp_path / "procedure.json")
    loaded = Procedure.from_dict(json.loads(path.read_text()))
    assert loaded.to_dict() == proc.to_dict()
    assert loaded.step("public-status").tool == "slack.post"


def test_sop_without_steps_is_rejected(tmp_path: Path):
    bad = tmp_path / "sop.md"
    bad.write_text("# Empty\n\n## Steps\n\nnothing numbered here\n")
    with pytest.raises(ValueError, match="no numbered steps"):
        parse_sop(bad)
