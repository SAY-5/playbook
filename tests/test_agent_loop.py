from pathlib import Path

from playbook.agent.loop import RunTrace, run_agent
from playbook.agent.prompt import PromptSpec
from playbook.agent.tools import KnowledgeBase, ToolExecutor
from playbook.config import Settings
from playbook.evals.scenarios import ScenarioSet
from playbook.ingest import ingest_procedure


def _run(settings: Settings, triage_dir: Path, scenario_id: str = "triage-01") -> RunTrace:
    proc = ingest_procedure(triage_dir)
    scenario = ScenarioSet.load(triage_dir / "scenarios.yaml").get(scenario_id)
    executor = ToolExecutor(settings, KnowledgeBase.from_file(triage_dir / "kb.json"))
    return run_agent(
        settings,
        PromptSpec(procedure_slug=proc.slug).render(proc),
        scenario.render(),
        executor,
        procedure_slug=proc.slug,
        prompt_version=1,
        scenario_id=scenario.id,
    )


def test_loop_records_every_turn_and_tool_call(settings: Settings, triage_dir: Path):
    trace = _run(settings, triage_dir)
    assert trace.status == "completed"
    assert trace.mode == "offline"
    assert trace.tool_names() == ["kb.search", "jira.create_issue", "jira.comment", "slack.post", "jira.transition"]
    assert len(trace.turns) == len(trace.tool_calls) + 1
    assert trace.turns[-1].stop_reason == "end_turn"
    assert all(t.tool_uses for t in trace.turns[:-1])
    create = trace.calls("jira.create_issue")[0]
    assert create.result["issue_key"].startswith("SUP-")
    assert create.error is None
    assert create.tool_use_id.startswith("toolu_")
    assert trace.final_text.startswith("Procedure complete")
    assert RunTrace.from_dict(trace.to_dict()).to_dict() == trace.to_dict()


def test_loop_is_bounded_by_max_steps(settings: Settings, triage_dir: Path):
    limited = Settings(**{**settings.__dict__, "max_steps": 2})
    trace = _run(limited, triage_dir)
    assert trace.status == "max_steps"
    assert len(trace.turns) == 2
    assert len(trace.tool_calls) == 2


def test_tool_errors_are_captured_not_raised(settings: Settings, triage_dir: Path):
    broken = Settings(**{**settings.__dict__, "slack_base_url": "http://127.0.0.1:9"})
    trace = _run(broken, triage_dir)
    post = trace.calls("slack.post")[0]
    assert post.error and post.result is None
    assert trace.status == "completed"
    assert trace.turns[-2].tool_uses[0]["name"] == "jira_transition"
