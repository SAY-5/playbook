"""Run artifact storage: local disk for development, S3 plus a DynamoDB index when deployed.

Everything the pipeline produces for one procedure is keyed by the procedure slug under one root,
on disk and in the bucket alike:

    <slug>/prompts/vN.json             PromptSpec
    <slug>/reports/vN.json             VersionReport
    <slug>/traces/vN/<scenario>.json   RunTrace
    <slug>/grades/vN/<scenario>.json   RunGrade
    <slug>/bank.json                   ScenarioBank
    <slug>/proposals/<id>.json         review records
    <slug>/promotions/<id>.json

so a deployment with `PLAYBOOK_RUN_STORE=s3` holds the same artifacts a local runs directory does,
and the Lambda runner can load any prompt version a reviewer promoted.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from playbook.agent.loop import RunTrace
from playbook.agent.prompt import PromptSpec
from playbook.config import Settings
from playbook.evals.bank import ScenarioBank
from playbook.evals.grader import RunGrade
from playbook.evals.report import VersionReport


class RunStore(Protocol):
    location: str

    def save_run(self, trace: RunTrace) -> str: ...
    def list_runs(self, procedure_slug: str, prompt_version: int) -> list[RunTrace]: ...
    def save_grade(self, grade: RunGrade) -> str: ...
    def list_grades(self, procedure_slug: str, prompt_version: int) -> list[RunGrade]: ...
    def save_prompt(self, spec: PromptSpec) -> str: ...
    def load_prompt(self, procedure_slug: str, version: int) -> PromptSpec: ...
    def prompt_versions(self, procedure_slug: str) -> list[int]: ...
    def save_report(self, report: VersionReport) -> str: ...
    def load_report(self, procedure_slug: str, version: int) -> VersionReport: ...
    def report_versions(self, procedure_slug: str) -> list[int]: ...
    def save_bank(self, bank: ScenarioBank) -> str: ...
    def load_bank(self, procedure_slug: str) -> ScenarioBank: ...
    def save_record(self, kind: str, procedure_slug: str, record_id: str, data: dict[str, Any]) -> str: ...
    def list_records(self, kind: str, procedure_slug: str) -> list[dict[str, Any]]: ...
    def procedures(self) -> list[str]: ...


def trace_key(procedure_slug: str, prompt_version: int, scenario_id: str) -> str:
    return f"{procedure_slug}/traces/v{prompt_version}/{scenario_id}.json"


def grade_key(procedure_slug: str, prompt_version: int, scenario_id: str) -> str:
    return f"{procedure_slug}/grades/v{prompt_version}/{scenario_id}.json"


def prompt_key(procedure_slug: str, version: int) -> str:
    return f"{procedure_slug}/prompts/v{version}.json"


def report_key(procedure_slug: str, version: int) -> str:
    return f"{procedure_slug}/reports/v{version}.json"


def bank_key(procedure_slug: str) -> str:
    return f"{procedure_slug}/bank.json"


def record_key(kind: str, procedure_slug: str, record_id: str) -> str:
    """Key for a review artifact (`proposals`, `promotions`) kept alongside the runs."""
    return f"{procedure_slug}/{kind}/{record_id}.json"


def _version_of(key: str) -> int | None:
    stem = key.rsplit("/", 1)[-1].removesuffix(".json")
    return int(stem[1:]) if stem.startswith("v") and stem[1:].isdigit() else None


class _KeyedStore:
    """The typed artifact methods, written over three primitives each backend supplies."""

    location: str

    def _put(self, key: str, data: dict[str, Any]) -> str:
        raise NotImplementedError

    def _get(self, key: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def _keys(self, prefix: str) -> list[str]:
        """Every key directly under `prefix` (a path ending in `/`), sorted."""
        raise NotImplementedError

    def _versions(self, prefix: str) -> list[int]:
        return sorted(v for v in (_version_of(k) for k in self._keys(prefix)) if v is not None)

    def _load_all(self, prefix: str) -> list[dict[str, Any]]:
        return [d for d in (self._get(k) for k in self._keys(prefix)) if d is not None]

    def save_run(self, trace: RunTrace) -> str:
        return self._put(trace_key(trace.procedure_slug, trace.prompt_version, trace.scenario_id), trace.to_dict())

    def list_runs(self, procedure_slug: str, prompt_version: int) -> list[RunTrace]:
        traces = [RunTrace.from_dict(d) for d in self._load_all(f"{procedure_slug}/traces/v{prompt_version}/")]
        return sorted(traces, key=lambda t: t.scenario_id)

    def save_grade(self, grade: RunGrade) -> str:
        return self._put(grade_key(grade.procedure_slug, grade.prompt_version, grade.scenario_id), grade.to_dict())

    def list_grades(self, procedure_slug: str, prompt_version: int) -> list[RunGrade]:
        grades = [RunGrade.from_dict(d) for d in self._load_all(f"{procedure_slug}/grades/v{prompt_version}/")]
        return sorted(grades, key=lambda g: g.scenario_id)

    def save_prompt(self, spec: PromptSpec) -> str:
        return self._put(prompt_key(spec.procedure_slug, spec.version), spec.to_dict())

    def load_prompt(self, procedure_slug: str, version: int) -> PromptSpec:
        data = self._get(prompt_key(procedure_slug, version))
        if data is None:
            raise KeyError(f"{procedure_slug} has no prompt v{version} in {self.location}")
        return PromptSpec.from_dict(data)

    def prompt_versions(self, procedure_slug: str) -> list[int]:
        return self._versions(f"{procedure_slug}/prompts/")

    def save_report(self, report: VersionReport) -> str:
        return self._put(report_key(report.procedure_slug, report.prompt_version), report.to_dict())

    def load_report(self, procedure_slug: str, version: int) -> VersionReport:
        data = self._get(report_key(procedure_slug, version))
        if data is None:
            raise KeyError(f"{procedure_slug} has no report for v{version} in {self.location}")
        return VersionReport.from_dict(data)

    def report_versions(self, procedure_slug: str) -> list[int]:
        return self._versions(f"{procedure_slug}/reports/")

    def save_bank(self, bank: ScenarioBank) -> str:
        return self._put(bank_key(bank.procedure_slug), bank.to_dict())

    def load_bank(self, procedure_slug: str) -> ScenarioBank:
        """The bank, or an empty one when the procedure has never banked a scenario."""
        data = self._get(bank_key(procedure_slug))
        return ScenarioBank.from_dict(data) if data is not None else ScenarioBank(procedure_slug=procedure_slug)

    def save_record(self, kind: str, procedure_slug: str, record_id: str, data: dict[str, Any]) -> str:
        return self._put(record_key(kind, procedure_slug, record_id), data)

    def list_records(self, kind: str, procedure_slug: str) -> list[dict[str, Any]]:
        return self._load_all(f"{procedure_slug}/{kind}/")

    def procedures(self) -> list[str]:
        """Slugs with at least one prompt version."""
        raise NotImplementedError


class LocalRunStore(_KeyedStore):
    def __init__(self, root: Path):
        self.root = root
        self.location = str(root)

    def _put(self, key: str, data: dict[str, Any]) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
        return str(path)

    def _get(self, key: str) -> dict[str, Any] | None:
        path = self.root / key
        return json.loads(path.read_text()) if path.exists() else None

    def _keys(self, prefix: str) -> list[str]:
        folder = self.root / prefix
        return sorted(f"{prefix}{p.name}" for p in folder.glob("*.json")) if folder.is_dir() else []

    def procedures(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and self.prompt_versions(p.name))


class S3RunStore(_KeyedStore):
    """Writes every artifact to S3 and indexes runs and review records in DynamoDB by procedure."""

    def __init__(self, settings: Settings):
        import boto3

        kwargs: dict[str, Any] = {}
        if settings.aws_endpoint_url:
            kwargs["endpoint_url"] = settings.aws_endpoint_url
        self.bucket = settings.s3_bucket
        self.table_name = settings.dynamodb_table
        self.location = f"s3://{self.bucket}"
        self.s3 = boto3.client("s3", **kwargs)
        self.ddb = boto3.resource("dynamodb", **kwargs).Table(self.table_name)

    def _put(self, key: str, data: dict[str, Any]) -> str:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=json.dumps(data).encode(), ContentType="application/json")
        return f"s3://{self.bucket}/{key}"

    def _get(self, key: str) -> dict[str, Any] | None:
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None
        return json.loads(body)

    def _keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return sorted(keys)

    def save_run(self, trace: RunTrace) -> str:
        key = trace_key(trace.procedure_slug, trace.prompt_version, trace.scenario_id)
        uri = self._put(key, trace.to_dict())
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
        return uri

    def list_runs(self, procedure_slug: str, prompt_version: int) -> list[RunTrace]:
        from boto3.dynamodb.conditions import Key

        items = self.ddb.query(
            KeyConditionExpression=Key("pk").eq(procedure_slug) & Key("sk").begins_with(f"v{prompt_version}#")
        )["Items"]
        traces = [RunTrace.from_dict(d) for d in (self._get(item["s3_key"]) for item in items) if d is not None]
        return sorted(traces, key=lambda t: t.scenario_id)

    def save_grade(self, grade: RunGrade) -> str:
        """Store the grade next to its trace and stamp the run's index item with the verdict."""
        key = grade_key(grade.procedure_slug, grade.prompt_version, grade.scenario_id)
        uri = self._put(key, grade.to_dict())
        self.ddb.update_item(
            Key={"pk": grade.procedure_slug, "sk": f"v{grade.prompt_version}#{grade.scenario_id}"},
            UpdateExpression="SET score = :score, passed = :passed, grade_key = :grade_key",
            ExpressionAttributeValues={
                ":score": Decimal(str(grade.score)),
                ":passed": grade.passed,
                ":grade_key": key,
            },
        )
        return uri

    def save_record(self, kind: str, procedure_slug: str, record_id: str, data: dict[str, Any]) -> str:
        key = record_key(kind, procedure_slug, record_id)
        uri = self._put(key, data)
        self.ddb.put_item(
            Item={
                "pk": procedure_slug,
                "sk": f"{kind}#{record_id}",
                "status": data.get("status", ""),
                "source_version": data.get("source_version", 0),
                "s3_key": key,
            }
        )
        return uri

    def list_records(self, kind: str, procedure_slug: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        items = self.ddb.query(KeyConditionExpression=Key("pk").eq(procedure_slug) & Key("sk").begins_with(f"{kind}#"))[
            "Items"
        ]
        out = [d for d in (self._get(i["s3_key"]) for i in items) if d is not None]
        return sorted(out, key=lambda d: d["id"])

    def procedures(self) -> list[str]:
        slugs: list[str] = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Delimiter="/"):
            slugs.extend(p["Prefix"].rstrip("/") for p in page.get("CommonPrefixes", []))
        return sorted(s for s in slugs if self.prompt_versions(s))


def make_store(settings: Settings) -> RunStore:
    if settings.run_store == "s3":
        return S3RunStore(settings)
    return LocalRunStore(settings.runs_dir)
