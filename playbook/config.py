"""Runtime configuration resolved from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "claude-sonnet-5"
FAKE_MODEL_PORT = 8801
FAKE_JIRA_PORT = 8802
FAKE_SLACK_PORT = 8803


@dataclass(frozen=True)
class Settings:
    """Everything the agent, tools and run store need to know about their environment."""

    live: bool = False
    model: str = DEFAULT_MODEL
    anthropic_api_key: str = "offline"
    anthropic_base_url: str | None = f"http://127.0.0.1:{FAKE_MODEL_PORT}"
    jira_base_url: str = f"http://127.0.0.1:{FAKE_JIRA_PORT}"
    jira_token: str = "offline"
    slack_base_url: str = f"http://127.0.0.1:{FAKE_SLACK_PORT}"
    slack_token: str = "offline"
    run_store: str = "local"
    runs_dir: Path = field(default_factory=lambda: Path("runs"))
    s3_bucket: str = "playbook-runs"
    dynamodb_table: str = "playbook-run-index"
    aws_endpoint_url: str | None = None
    max_steps: int = 12

    @classmethod
    def from_env(cls, live: bool = False) -> Settings:
        env = os.environ
        if live:
            key = env.get("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError("--live requires ANTHROPIC_API_KEY")
            return cls(
                live=True,
                model=env.get("PLAYBOOK_MODEL", DEFAULT_MODEL),
                anthropic_api_key=key,
                anthropic_base_url=env.get("ANTHROPIC_BASE_URL"),
                jira_base_url=env.get("JIRA_BASE_URL", cls.jira_base_url),
                jira_token=env.get("JIRA_TOKEN", ""),
                slack_base_url=env.get("SLACK_BASE_URL", "https://slack.com"),
                slack_token=env.get("SLACK_TOKEN", ""),
                run_store=env.get("PLAYBOOK_RUN_STORE", "local"),
                runs_dir=Path(env.get("PLAYBOOK_RUNS_DIR", "runs")),
                s3_bucket=env.get("PLAYBOOK_S3_BUCKET", cls.s3_bucket),
                dynamodb_table=env.get("PLAYBOOK_DDB_TABLE", cls.dynamodb_table),
                aws_endpoint_url=env.get("AWS_ENDPOINT_URL"),
                max_steps=int(env.get("PLAYBOOK_MAX_STEPS", cls.max_steps)),
            )
        return cls(
            live=False,
            model=env.get("PLAYBOOK_MODEL", DEFAULT_MODEL),
            anthropic_base_url=env.get("PLAYBOOK_FAKE_MODEL_URL", cls.anthropic_base_url),
            jira_base_url=env.get("PLAYBOOK_FAKE_JIRA_URL", cls.jira_base_url),
            slack_base_url=env.get("PLAYBOOK_FAKE_SLACK_URL", cls.slack_base_url),
            run_store=env.get("PLAYBOOK_RUN_STORE", "local"),
            runs_dir=Path(env.get("PLAYBOOK_RUNS_DIR", "runs")),
            s3_bucket=env.get("PLAYBOOK_S3_BUCKET", cls.s3_bucket),
            dynamodb_table=env.get("PLAYBOOK_DDB_TABLE", cls.dynamodb_table),
            aws_endpoint_url=env.get("AWS_ENDPOINT_URL"),
            max_steps=int(env.get("PLAYBOOK_MAX_STEPS", cls.max_steps)),
        )
