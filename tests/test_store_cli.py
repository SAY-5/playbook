import importlib.util
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from playbook.agent.loop import RunTrace
from playbook.agent.prompt import Correction, PromptSpec
from playbook.agent.store import LocalRunStore, S3RunStore
from playbook.cli import main
from playbook.config import Settings
from playbook.evals.report import VersionReport
from playbook.feedback.approval import PromotionLog
from playbook.runner import Workspace

LOCALSTACK = os.environ.get("AWS_ENDPOINT_URL")
SLUG = "support-triage"


def _trace(version: int, scenario: str) -> RunTrace:
    return RunTrace(
        run_id=f"r{version}{scenario}",
        procedure_slug=SLUG,
        prompt_version=version,
        scenario_id=scenario,
        mode="offline",
        model="fake",
        system_prompt="s",
        user_message="u",
        started_at="t",
        status="completed",
    )


def _report(version: int) -> VersionReport:
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
        forbidden_violations=0,
    )


def test_local_store_keys_every_artifact_by_slug(tmp_path: Path):
    store = LocalRunStore(tmp_path)
    store.save_run(_trace(1, "b"))
    store.save_run(_trace(1, "a"))
    store.save_run(_trace(2, "a"))
    assert [t.scenario_id for t in store.list_runs(SLUG, 1)] == ["a", "b"]
    assert store.list_runs(SLUG, 3) == []
    assert (tmp_path / SLUG / "traces" / "v2" / "a.json").exists()

    v1 = PromptSpec(procedure_slug=SLUG)
    store.save_prompt(v1)
    store.save_prompt(v1.with_corrections([Correction("escalate", "rule", "crit", 1)], notes="n"))
    store.save_report(_report(1))
    assert store.prompt_versions(SLUG) == [1, 2] and store.report_versions(SLUG) == [1]
    assert store.load_report(SLUG, 1).pass_rate == 1.0
    assert store.procedures() == [SLUG]
    assert (tmp_path / SLUG / "prompts" / "v2.json").exists()
    assert (tmp_path / SLUG / "reports" / "v1.json").exists()
    with pytest.raises(KeyError, match="no report for v2"):
        store.load_report(SLUG, 2)
    store.save_record("proposals", SLUG, "p1-01", {"id": "p1-01", "status": "pending"})
    assert (tmp_path / SLUG / "proposals" / "p1-01.json").exists()
    assert store.list_records("proposals", SLUG)[0]["id"] == "p1-01"
    assert store.load_bank(SLUG).entries == []


def _localstack_settings(fakes, runs_dir: Path, **overrides) -> Settings:
    settings = Settings(
        run_store="s3",
        aws_endpoint_url=LOCALSTACK,
        anthropic_base_url=fakes["model"].url,
        jira_base_url=fakes["jira"].url,
        slack_base_url=fakes["slack"].url,
        runs_dir=runs_dir,
        **overrides,
    )
    import boto3

    s3 = boto3.client("s3", endpoint_url=settings.aws_endpoint_url)
    if settings.s3_bucket not in [b["Name"] for b in s3.list_buckets()["Buckets"]]:
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
    return settings


@pytest.mark.skipif(not LOCALSTACK, reason="needs LocalStack (AWS_ENDPOINT_URL)")
def test_s3_store_against_localstack(fakes, tmp_path: Path):
    settings = _localstack_settings(fakes, tmp_path)
    store = S3RunStore(settings)
    uri = store.save_run(_trace(7, "s3-a"))
    assert uri == f"s3://{settings.s3_bucket}/{SLUG}/traces/v7/s3-a.json"
    assert [t.run_id for t in store.list_runs(SLUG, 7)] == ["r7s3-a"]
    store.save_prompt(PromptSpec(procedure_slug=SLUG, version=7))
    store.save_report(_report(7))
    assert 7 in store.prompt_versions(SLUG) and 7 in store.report_versions(SLUG)
    assert store.load_prompt(SLUG, 7).version == 7 and store.load_report(SLUG, 7).prompt_version == 7
    assert SLUG in store.procedures()


def _lambda_handler():
    """deploy/lambda is not a package (and `lambda` is a keyword), so load the handler by path."""
    path = Path(__file__).resolve().parent.parent / "deploy" / "lambda" / "handler.py"
    spec = importlib.util.spec_from_file_location("lambda_handler", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not LOCALSTACK, reason="needs LocalStack (AWS_ENDPOINT_URL)")
def test_lambda_handler_runs_a_stored_version_from_s3(fakes, tmp_path: Path, monkeypatch):
    run_message = _lambda_handler().run_message

    monkeypatch.setenv("PLAYBOOK_PROCEDURES_DIR", str(Path(__file__).resolve().parent.parent / "procedures"))
    settings = _localstack_settings(
        fakes, tmp_path, s3_bucket="playbook-handler-test", dynamodb_table="playbook-handler-index"
    )
    store = S3RunStore(settings)
    ws = Workspace(Path(os.environ["PLAYBOOK_PROCEDURES_DIR"]) / "support_triage", tmp_path, store)
    v1 = ws.prompt()
    v2 = v1.with_corrections(
        [Correction("create-ticket", 'Set summary to "[{severity}] {title}".', "s", 1)], notes="v2"
    )
    v3 = v2.with_corrections(
        [Correction("escalate", "When posting to Slack, do not include the customer email.", "p", 2)], notes="v3"
    )
    store.save_prompt(v2)
    store.save_prompt(v3)
    assert store.prompt_versions(SLUG) == [1, 2, 3]

    message = {"procedure": "support_triage", "scenario_id": "triage-01"}
    with pytest.raises(ValueError, match="no version is promoted"):
        run_message(message, settings)

    result = run_message({**message, "prompt_version": 3}, settings)
    assert result["prompt_version"] == 3 and result["status"] == "completed"
    traces = store.list_runs(SLUG, 3)
    assert [t.scenario_id for t in traces] == ["triage-01"] and traces[0].run_id == result["run_id"]
    assert v3.corrections[-1].text in traces[0].system_prompt
    grades = store.list_grades(SLUG, 3)
    assert [g.run_id for g in grades] == [result["run_id"]] and grades[0].passed == result["passed"]
    item = store.ddb.get_item(Key={"pk": SLUG, "sk": "v3#triage-01"})["Item"]
    assert item["grade_key"] == f"{SLUG}/grades/v3/triage-01.json" and float(item["score"]) == result["score"]

    PromotionLog(store, SLUG).decide(_report(2), [], "dana")
    assert run_message(message, settings)["prompt_version"] == 2
    assert [t.scenario_id for t in store.list_runs(SLUG, 2)] == ["triage-01"]


def test_cli_ingest_eval_and_report(settings: Settings, triage_dir: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLAYBOOK_FAKE_MODEL_URL", settings.anthropic_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_JIRA_URL", settings.jira_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_SLACK_URL", settings.slack_base_url)
    runs = tmp_path / "cli-runs"
    cli = CliRunner()
    r = cli.invoke(main, ["ingest", str(triage_dir), "--runs-dir", str(runs)])
    assert r.exit_code == 0, r.output
    assert "5 steps" in r.output and "walkthrough.md:7" in r.output
    assert (runs / SLUG / "procedure.json").exists()
    r = cli.invoke(main, ["eval", str(triage_dir), "--runs-dir", str(runs)])
    assert r.exit_code == 0, r.output
    assert "pass rate" in r.output and "FAIL triage-01" in r.output
    assert sorted(p.name for p in (runs / SLUG).iterdir()) == [
        "artifacts",
        "grades",
        "procedure.json",
        "prompts",
        "reports",
        "traces",
    ]
    r = cli.invoke(main, ["improve", str(triage_dir), "--runs-dir", str(runs), "--dry-run"])
    assert r.exit_code == 0 and "[create-ticket]" in r.output
    r = cli.invoke(main, ["improve", str(triage_dir), "--runs-dir", str(runs), "--auto-approve"])
    assert r.exit_code == 0 and "created v2" in r.output
    r = cli.invoke(main, ["eval", str(triage_dir), "--runs-dir", str(runs), "--compare", "1"])
    assert r.exit_code == 0 and "| v1" in r.output and "| v2" in r.output
    r = cli.invoke(main, ["report", str(triage_dir), "--runs-dir", str(runs), "--inbox"])
    assert r.exit_code == 0, r.output
    assert "Jira inbox" in r.output and "#support-escalations" in r.output
    r = cli.invoke(main, ["run", str(triage_dir), "--runs-dir", str(runs), "--scenario", "triage-02"])
    assert r.exit_code == 0 and "triage-02: completed" in r.output


def test_cli_diff_promote_and_audit(settings: Settings, triage_dir: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLAYBOOK_FAKE_MODEL_URL", settings.anthropic_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_JIRA_URL", settings.jira_base_url)
    monkeypatch.setenv("PLAYBOOK_FAKE_SLACK_URL", settings.slack_base_url)
    runs = tmp_path / "gate-runs"
    where = ["--runs-dir", str(runs)]
    cli = CliRunner()
    r = cli.invoke(main, ["loop", str(triage_dir), *where, "--max-rounds", "4"])
    assert r.exit_code == 0, r.output
    assert sorted(p.name for p in (runs / SLUG).iterdir()) == [
        "artifacts",
        "grades",
        "procedure.json",
        "prompts",
        "proposals",
        "reports",
        "traces",
    ]
    assert sorted(p.name for p in (runs / SLUG / "traces").iterdir()) == ["v1", "v2", "v3"]

    r = cli.invoke(main, ["diff", str(triage_dir), *where, "--from", "1", "--to", "2"])
    assert r.exit_code == 0, r.output
    assert "0 step(s) added, 0 removed, 2 changed" in r.output
    assert "changed [create-ticket]" in r.output and '+ Set summary to "[{severity}] {title}".' in r.output

    r = cli.invoke(main, ["promote", str(triage_dir), *where, "--version", "1", "--as", "dana"])
    assert r.exit_code == 1
    assert "v1 blocked by dana" in r.output and "forbidden-action: no_pii_in_slack" in r.output

    r = cli.invoke(main, ["promote", str(triage_dir), *where, "--as", "dana", "--note", "leaks cleared"])
    assert r.exit_code == 0, r.output
    assert "v3 promoted by dana" in r.output

    r = cli.invoke(main, ["review", "audit", str(triage_dir), *where])
    assert r.exit_code == 0, r.output
    assert "audit trail" in r.output and "blocked   v1" in r.output and "promoted  v3" in r.output
    assert r.output.count(" approved  p") >= 10
    assert sorted(p.name for p in (runs / SLUG / "promotions").iterdir()) == ["d1-01.json", "d3-01.json"]


def test_live_settings_require_the_key_and_real_tool_credentials(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "JIRA_BASE_URL", "JIRA_TOKEN", "SLACK_TOKEN", "PLAYBOOK_TOOLS"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        Settings.from_env(live=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.raises(RuntimeError, match="JIRA_BASE_URL, JIRA_TOKEN, SLACK_TOKEN"):
        Settings.from_env(live=True)
    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
    monkeypatch.setenv("JIRA_TOKEN", "j")
    with pytest.raises(RuntimeError, match=r"requires SLACK_TOKEN \("):
        Settings.from_env(live=True)
    monkeypatch.setenv("SLACK_TOKEN", "s")
    real = Settings.from_env(live=True)
    assert real.tools == "real"
    assert (real.jira_base_url, real.slack_base_url) == ("https://jira.example.com", "https://slack.com")

    monkeypatch.delenv("JIRA_BASE_URL")
    monkeypatch.setenv("PLAYBOOK_TOOLS", "fake")
    monkeypatch.setenv("PLAYBOOK_FAKE_JIRA_URL", "http://127.0.0.1:9902")
    fake = Settings.from_env(live=True)
    assert fake.live and fake.tools == "fake"
    assert (fake.jira_base_url, fake.jira_token, fake.slack_token) == ("http://127.0.0.1:9902", "offline", "offline")
