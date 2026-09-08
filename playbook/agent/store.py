"""Run artifact storage: local disk for development, S3 plus a DynamoDB index when deployed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from playbook.agent.loop import RunTrace
from playbook.config import Settings


class RunStore(Protocol):
    def save_run(self, trace: RunTrace) -> str: ...
    def list_runs(self, procedure_slug: str, prompt_version: int) -> list[RunTrace]: ...


def run_key(trace: RunTrace) -> str:
    return f"runs/{trace.procedure_slug}/v{trace.prompt_version}/{trace.scenario_id}.json"


class LocalRunStore:
    def __init__(self, root: Path):
        self.root = root

    def save_run(self, trace: RunTrace) -> str:
        path = self.root / run_key(trace)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(trace.to_dict(), indent=2) + "\n")
        return str(path)

    def list_runs(self, procedure_slug: str, prompt_version: int) -> list[RunTrace]:
        folder = self.root / "runs" / procedure_slug / f"v{prompt_version}"
        return [RunTrace.from_dict(json.loads(p.read_text())) for p in sorted(folder.glob("*.json"))]


class S3RunStore:
    """Writes each trace to S3 and indexes it in DynamoDB keyed by procedure and run id."""

    def __init__(self, settings: Settings):
        import boto3

        kwargs: dict[str, Any] = {}
        if settings.aws_endpoint_url:
            kwargs["endpoint_url"] = settings.aws_endpoint_url
        self.bucket = settings.s3_bucket
        self.table_name = settings.dynamodb_table
        self.s3 = boto3.client("s3", **kwargs)
        self.ddb = boto3.resource("dynamodb", **kwargs).Table(self.table_name)

    def save_run(self, trace: RunTrace) -> str:
        key = run_key(trace)
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(trace.to_dict()).encode(),
            ContentType="application/json",
        )
        self.ddb.put_item(
            Item={
                "pk": trace.procedure_slug,
                "sk": f"v{trace.prompt_version}#{trace.scenario_id}",
                "run_id": trace.run_id,
                "status": trace.status,
                "mode": trace.mode,
                "s3_key": key,
                "started_at": trace.started_at,
            }
        )
        return f"s3://{self.bucket}/{key}"

    def list_runs(self, procedure_slug: str, prompt_version: int) -> list[RunTrace]:
        from boto3.dynamodb.conditions import Key

        items = self.ddb.query(
            KeyConditionExpression=Key("pk").eq(procedure_slug) & Key("sk").begins_with(f"v{prompt_version}#")
        )["Items"]
        traces = []
        for item in items:
            body = self.s3.get_object(Bucket=self.bucket, Key=item["s3_key"])["Body"].read()
            traces.append(RunTrace.from_dict(json.loads(body)))
        return sorted(traces, key=lambda t: t.scenario_id)


def make_store(settings: Settings) -> RunStore:
    if settings.run_store == "s3":
        return S3RunStore(settings)
    return LocalRunStore(settings.runs_dir)
