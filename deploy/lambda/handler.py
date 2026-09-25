"""SQS-triggered Lambda entry point: one scenario run per message.

Message body: {"procedure": "support_triage", "scenario_id": "triage-01", "prompt_version": 3}
`prompt_version` is optional; without it the promoted version is used, and a procedure with no
promoted version is refused so the message lands in the dead-letter queue instead of running an
unreviewed prompt. Prompts, traces, grades and promotions all come from the run store
(`PLAYBOOK_RUN_STORE=s3` in the deployed function). Credentials come from the Secrets Manager
secret named by PLAYBOOK_SECRET_ID and are exported to the environment before
Settings.from_env(live=True) reads them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import boto3

from playbook.agent.store import make_store
from playbook.config import Settings
from playbook.feedback.approval import PromotionLog
from playbook.runner import Runner, Workspace

_loaded = False


def _load_secrets() -> None:
    global _loaded
    if _loaded:
        return
    secret_id = os.environ.get("PLAYBOOK_SECRET_ID")
    if secret_id:
        client = boto3.client("secretsmanager", endpoint_url=os.environ.get("AWS_ENDPOINT_URL"))
        payload = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
        for key, value in payload.items():
            if value and not os.environ.get(key):
                os.environ[key] = value
    _loaded = True


def _settings_from_env() -> Settings:
    _load_secrets()
    os.environ.setdefault("PLAYBOOK_RUNS_DIR", "/tmp/playbook")
    return Settings.from_env(live=True)


def run_message(body: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """Run and grade one scenario. `settings` is taken from the environment when not given."""
    settings = settings or _settings_from_env()
    procedures = Path(os.environ.get("PLAYBOOK_PROCEDURES_DIR", "procedures"))
    store = make_store(settings)
    ws = Workspace(procedures / body["procedure"], settings.runs_dir, store)
    ws.ingest()
    version = body.get("prompt_version")
    if version is None:
        version = PromotionLog(store, ws.slug).current()
        if version is None:
            raise ValueError(f"{ws.slug}: the message names no prompt_version and no version is promoted")
    spec = ws.prompt(int(version))
    scenario = ws.scenarios().get(body["scenario_id"])
    runner = Runner(settings, ws)
    try:
        trace = runner.run_scenario(spec, scenario)
        grade = runner.grade(trace, scenario)
    finally:
        runner.close()
    return {
        "run_id": trace.run_id,
        "scenario_id": scenario.id,
        "prompt_version": spec.version,
        "status": trace.status,
        "score": grade.score,
        "passed": grade.passed,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    results = [run_message(json.loads(record["body"])) for record in event.get("Records", [])]
    return {"processed": len(results), "results": results}
