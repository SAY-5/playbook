"""SQS-triggered Lambda entry point: one scenario run per message.

Message body: {"procedure": "support_triage", "scenario_id": "triage-01", "prompt_version": 3}
Credentials come from the Secrets Manager secret named by PLAYBOOK_SECRET_ID and are exported to
the environment before Settings.from_env(live=True) reads them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import boto3

from playbook.config import Settings
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


def run_message(body: dict[str, Any]) -> dict[str, Any]:
    _load_secrets()
    settings = Settings.from_env(live=True)
    procedures = Path(os.environ.get("PLAYBOOK_PROCEDURES_DIR", "procedures"))
    ws = Workspace(procedures / body["procedure"], Path("/tmp/playbook"))
    ws.ingest()
    runner = Runner(settings, ws)
    version = body.get("prompt_version")
    spec = ws.prompt(int(version)) if version else ws.prompt()
    scenario = ws.scenarios().get(body["scenario_id"])
    trace = runner.run_scenario(spec, scenario)
    grade = runner.grade(trace, scenario)
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
