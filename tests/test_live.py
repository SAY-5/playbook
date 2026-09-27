"""Live-mode test: real Anthropic Messages API with the local Jira and Slack fakes as tools."""

import os
from pathlib import Path

import pytest

from playbook.config import Settings
from playbook.runner import Runner, Workspace

pytestmark = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")


def test_live_model_completes_a_triage_scenario(fakes, tmp_path: Path, triage_dir: Path, monkeypatch):
    monkeypatch.setenv("PLAYBOOK_TOOLS", "fake")
    monkeypatch.setenv("PLAYBOOK_FAKE_JIRA_URL", fakes["jira"].url)
    monkeypatch.setenv("PLAYBOOK_FAKE_SLACK_URL", fakes["slack"].url)
    monkeypatch.setenv("PLAYBOOK_RUNS_DIR", str(tmp_path))
    settings = Settings.from_env(live=True)
    assert settings.tools == "fake" and settings.jira_base_url == fakes["jira"].url
    ws = Workspace(triage_dir, tmp_path)
    ws.ingest()
    runner = Runner(settings, ws)
    scenario = ws.scenarios().get("triage-01")
    trace = runner.run_scenario(ws.prompt(), scenario)
    runner.close()
    assert trace.mode == "live"
    assert trace.tool_endpoints["kind"] == "fake"
    assert trace.status == "completed", trace.error
    assert "jira.create_issue" in trace.tool_names()
    grade = runner.grade(trace, scenario)
    assert grade.required_actions_made >= 1
