"""Live-mode test: real Anthropic Messages API with the local Jira and Slack fakes as tools."""

import os
from pathlib import Path

import pytest

from playbook.config import Settings
from playbook.runner import Runner, Workspace

pytestmark = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")


def test_live_model_completes_a_triage_scenario(fakes, tmp_path: Path, triage_dir: Path):
    base = Settings.from_env(live=True)
    settings = Settings(
        **{
            **base.__dict__,
            "jira_base_url": fakes["jira"].url,
            "slack_base_url": fakes["slack"].url,
            "runs_dir": tmp_path,
        }
    )
    ws = Workspace(triage_dir, tmp_path)
    ws.ingest()
    runner = Runner(settings, ws)
    scenario = ws.scenarios().get("triage-01")
    trace = runner.run_scenario(ws.prompt(), scenario)
    assert trace.mode == "live"
    assert trace.status == "completed", trace.error
    assert "jira.create_issue" in trace.tool_names()
    grade = runner.grade(trace, scenario)
    assert grade.required_actions_made >= 1
