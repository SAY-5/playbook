from __future__ import annotations

from pathlib import Path

import pytest

from fakes import jira_server, model_server, slack_server
from playbook.config import Settings

ROOT = Path(__file__).resolve().parent.parent
PROCEDURES = ROOT / "procedures"


@pytest.fixture(scope="session")
def fakes():
    servers = {
        "model": model_server.serve(0),
        "jira": jira_server.serve(0),
        "slack": slack_server.serve(0),
    }
    yield servers
    for s in servers.values():
        s.stop()


@pytest.fixture
def settings(fakes, tmp_path: Path) -> Settings:
    return Settings(
        anthropic_base_url=fakes["model"].url,
        jira_base_url=fakes["jira"].url,
        slack_base_url=fakes["slack"].url,
        runs_dir=tmp_path / "runs",
    )


@pytest.fixture
def triage_dir() -> Path:
    return PROCEDURES / "support_triage"


@pytest.fixture
def incident_dir() -> Path:
    return PROCEDURES / "incident_comms"
