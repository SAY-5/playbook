import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from playbook.agent.loop import RunTrace
from playbook.agent.store import LocalRunStore, S3RunStore
from playbook.cli import main
from playbook.config import Settings


def _trace(version: int, scenario: str) -> RunTrace:
    return RunTrace(
        run_id=f"r{version}{scenario}",
        procedure_slug="support-triage",
        prompt_version=version,
        scenario_id=scenario,
        mode="offline",
        model="fake",
        system_prompt="s",
        user_message="u",
        started_at="t",
        status="completed",
    )


def test_local_store_round_trip(tmp_path: Path):
    store = LocalRunStore(tmp_path)
    store.save_run(_trace(1, "b"))
    store.save_run(_trace(1, "a"))
    store.save_run(_trace(2, "a"))
    assert [t.scenario_id for t in store.list_runs("support-triage", 1)] == ["a", "b"]
    assert store.list_runs("support-triage", 3) == []
    assert (tmp_path / "runs/support-triage/v2/a.json").exists()


@pytest.mark.skipif(not os.environ.get("AWS_ENDPOINT_URL"), reason="needs LocalStack (AWS_ENDPOINT_URL)")
def test_s3_store_against_localstack():
    import boto3

    settings = Settings(run_store="s3", aws_endpoint_url=os.environ["AWS_ENDPOINT_URL"])
    s3 = boto3.client("s3", endpoint_url=settings.aws_endpoint_url)
    s3.create_bucket(Bucket=settings.s3_bucket)
    ddb = boto3.client("dynamodb", endpoint_url=settings.aws_endpoint_url)
    if settings.dynamodb_table not in ddb.list_tables()["TableNames"]:
        ddb.create_table(
            TableName=settings.dynamodb_table,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
    store = S3RunStore(settings)
    uri = store.save_run(_trace(7, "s3-a"))
    assert uri == f"s3://{settings.s3_bucket}/runs/support-triage/v7/s3-a.json"
    assert [t.run_id for t in store.list_runs("support-triage", 7)] == ["r7s3-a"]


def test_cli_ingest_eval_and_report(settings: Settings, triage_dir: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLAYBOOK_FAKE_MODEL_URL", settings.anthropic_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_JIRA_URL", settings.jira_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_SLACK_URL", settings.slack_base_url)
    runs = tmp_path / "cli-runs"
    cli = CliRunner()
    r = cli.invoke(main, ["ingest", str(triage_dir), "--runs-dir", str(runs)])
    assert r.exit_code == 0, r.output
    assert "5 steps" in r.output and "walkthrough.md:7" in r.output
    r = cli.invoke(main, ["eval", str(triage_dir), "--runs-dir", str(runs)])
    assert r.exit_code == 0, r.output
    assert "pass rate" in r.output and "FAIL triage-01" in r.output
    r = cli.invoke(main, ["improve", str(triage_dir), "--runs-dir", str(runs), "--dry-run"])
    assert r.exit_code == 0 and "[create-ticket]" in r.output
    r = cli.invoke(main, ["improve", str(triage_dir), "--runs-dir", str(runs)])
    assert r.exit_code == 0 and "created v2" in r.output
    r = cli.invoke(main, ["eval", str(triage_dir), "--runs-dir", str(runs), "--compare", "1"])
    assert r.exit_code == 0 and "| v1" in r.output and "| v2" in r.output
    r = cli.invoke(main, ["report", str(triage_dir), "--runs-dir", str(runs), "--inbox"])
    assert r.exit_code == 0, r.output
    assert "Jira inbox" in r.output and "#support-escalations" in r.output
    r = cli.invoke(main, ["run", str(triage_dir), "--runs-dir", str(runs), "--scenario", "triage-02"])
    assert r.exit_code == 0 and "triage-02: completed" in r.output


def test_live_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        Settings.from_env(live=True)
