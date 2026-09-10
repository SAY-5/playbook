"""Operational view of a runs directory: what exists, how it scored, and what it cost.

Everything the pipeline produces lands under one runs directory: prompt versions, graded reports,
run traces, proposals and promotions. This module reads that directory back and answers the
questions an operator asks between runs, and writes the per-run JSON artifact that carries the same
figures out of the machine.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playbook.agent.loop import RunTrace
from playbook.agent.prompt import PromptSpec
from playbook.agent.store import RunStore
from playbook.evals.report import VersionReport
from playbook.feedback.approval import PromotionLog
from playbook.feedback.review import ReviewQueue


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


@dataclass
class Metrics:
    """Tool-call counts and latency over a set of run traces."""

    runs: int = 0
    tool_calls: int = 0
    by_tool: dict[str, int] = field(default_factory=dict)
    calls_per_run: float = 0.0
    tool_ms_mean: float = 0.0
    tool_ms_p95: int = 0
    tool_ms_max: int = 0
    run_ms_mean: float = 0.0
    run_ms_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def measure(traces: list[RunTrace]) -> Metrics:
    if not traces:
        return Metrics()
    call_ms = [c.duration_ms for t in traces for c in t.tool_calls]
    by_tool: dict[str, int] = {}
    for t in traces:
        for c in t.tool_calls:
            by_tool[c.name] = by_tool.get(c.name, 0) + 1
    run_ms = [t.duration_ms for t in traces]
    return Metrics(
        runs=len(traces),
        tool_calls=len(call_ms),
        by_tool=dict(sorted(by_tool.items())),
        calls_per_run=round(len(call_ms) / len(traces), 2),
        tool_ms_mean=round(sum(call_ms) / len(call_ms), 2) if call_ms else 0.0,
        tool_ms_p95=_percentile(call_ms, 0.95),
        tool_ms_max=max(call_ms, default=0),
        run_ms_mean=round(sum(run_ms) / len(traces), 2),
        run_ms_total=sum(run_ms),
    )


@dataclass
class ProcedureOps:
    slug: str
    directory: str
    versions: list[int]
    promoted_version: int | None
    scenarios: int
    pass_rates: list[tuple[int, float]]
    open_forbidden: int
    open_forbidden_criteria: list[str]
    pending_proposals: int
    last_run_scenario: str
    last_run_version: int
    last_run_at: str
    last_run_ms: int
    metrics: Metrics

    @property
    def latest_version(self) -> int | None:
        return self.versions[-1] if self.versions else None


@dataclass
class OpsSummary:
    generated_at: str
    runs_dir: str
    procedures: list[ProcedureOps]

    @property
    def total_versions(self) -> int:
        return sum(len(p.versions) for p in self.procedures)

    @property
    def total_scenarios(self) -> int:
        return sum(p.scenarios for p in self.procedures)

    @property
    def open_forbidden(self) -> int:
        return sum(p.open_forbidden for p in self.procedures)

    @property
    def total_runs(self) -> int:
        return sum(p.metrics.runs for p in self.procedures)

    @property
    def total_tool_calls(self) -> int:
        return sum(p.metrics.tool_calls for p in self.procedures)


def _versions(prompts_dir: Path) -> list[int]:
    return sorted(int(p.stem[1:]) for p in prompts_dir.glob("v*.json") if p.stem[1:].isdigit())


def _procedure_ops(out_dir: Path, store: RunStore) -> ProcedureOps | None:
    prompts_dir = out_dir / "prompts"
    versions = _versions(prompts_dir)
    if not versions:
        return None
    slug = PromptSpec.load(prompts_dir, versions[0]).procedure_slug
    reports_dir = out_dir / "reports"
    reports = [VersionReport.load(reports_dir, v) for v in versions if (reports_dir / f"v{v}.json").exists()]
    traces = [t for v in versions for t in store.list_runs(slug, v)]
    latest = reports[-1] if reports else None
    offenders = sorted(
        {r.id for g in (latest.grades if latest else []) for r in g.results if r.forbidden and not r.passed}
    )
    last = max(traces, key=lambda t: (t.started_at, t.prompt_version, t.scenario_id), default=None)
    return ProcedureOps(
        slug=slug,
        directory=out_dir.name,
        versions=versions,
        promoted_version=PromotionLog(store, slug).current(),
        scenarios=latest.scenarios if latest else 0,
        pass_rates=[(r.prompt_version, r.pass_rate) for r in reports],
        open_forbidden=latest.forbidden_violations if latest else 0,
        open_forbidden_criteria=offenders,
        pending_proposals=len(ReviewQueue(store, slug).pending()),
        last_run_scenario=last.scenario_id if last else "",
        last_run_version=last.prompt_version if last else 0,
        last_run_at=last.started_at if last else "",
        last_run_ms=last.duration_ms if last else 0,
        metrics=measure(traces),
    )


def collect_ops(runs_dir: Path, store: RunStore) -> OpsSummary:
    """Read every procedure under `runs_dir` that has at least one prompt version."""
    procedures = []
    for out_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.exists() else []:
        ops = _procedure_ops(out_dir, store)
        if ops is not None:
            procedures.append(ops)
    return OpsSummary(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        runs_dir=str(runs_dir),
        procedures=procedures,
    )


def format_ops(summary: OpsSummary) -> str:
    lines = [
        f"playbook ops at {summary.generated_at}: {len(summary.procedures)} procedure(s), "
        f"{summary.total_versions} prompt version(s), {summary.total_scenarios} scenario(s), "
        f"{summary.open_forbidden} open forbidden action(s), {summary.total_runs} run(s), "
        f"{summary.total_tool_calls} tool call(s)"
    ]
    for p in summary.procedures:
        promoted = f"promoted v{p.promoted_version}" if p.promoted_version else "nothing promoted"
        rates = ", ".join(f"v{v} {rate:.1%}" for v, rate in p.pass_rates) or "not graded"
        forbidden = f"{p.open_forbidden}" + (
            f" ({', '.join(p.open_forbidden_criteria)})" if p.open_forbidden_criteria else ""
        )
        m = p.metrics
        lines.extend(
            [
                f"{p.slug}",
                f"  versions: {' '.join(f'v{v}' for v in p.versions)} (latest v{p.latest_version}, {promoted})",
                f"  pass rate: {rates}",
                f"  open forbidden actions: {forbidden}",
                f"  pending proposals: {p.pending_proposals}",
                f"  last run: {p.last_run_scenario or '-'} on v{p.last_run_version} at "
                f"{p.last_run_at or '-'} in {p.last_run_ms} ms",
                f"  runs: {m.runs}, tool calls {m.tool_calls} ({m.calls_per_run} per run), "
                f"tool latency mean {m.tool_ms_mean} ms, p95 {m.tool_ms_p95} ms, max {m.tool_ms_max} ms",
                f"  tools: {', '.join(f'{name} {count}' for name, count in m.by_tool.items()) or '-'}",
            ]
        )
    return "\n".join(lines)


def write_run_artifact(
    artifacts_dir: Path,
    command: str,
    procedure_slug: str,
    reports: list[VersionReport],
    traces: list[RunTrace],
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write one JSON artifact describing this command run: versions, scores and measured cost."""
    now = datetime.now(UTC)
    artifact = {
        "artifact_id": f"{command}-{now.strftime('%Y%m%dT%H%M%S')}",
        "command": command,
        "procedure": procedure_slug,
        "written_at": now.isoformat(timespec="seconds"),
        "versions": [
            {
                "version": r.prompt_version,
                "scenarios": r.scenarios,
                "passed": r.passed,
                "pass_rate": r.pass_rate,
                "mean_score": r.mean_score,
                "forbidden_violations": r.forbidden_violations,
                "failing": sorted(g.scenario_id for g in r.grades if not g.passed),
            }
            for r in reports
        ],
        "metrics": measure(traces).to_dict(),
        **(extra or {}),
    }
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / f"{artifact['artifact_id']}.json"
    path.write_text(json.dumps(artifact, indent=2) + "\n")
    return path
