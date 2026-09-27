"""Ties ingest, prompt, agent loop, store and grader together for one procedure."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import httpx

from playbook.agent.loop import RunTrace, make_client, run_agent
from playbook.agent.prompt import PromptSpec
from playbook.agent.store import LocalRunStore, RunStore
from playbook.agent.tools import KnowledgeBase, ToolExecutor
from playbook.config import Settings
from playbook.evals.bank import ScenarioBank
from playbook.evals.grader import Grader, RunGrade
from playbook.evals.judge import Judge, LiveJudge, OfflineJudge
from playbook.evals.report import VersionReport, build_report
from playbook.evals.rubric import Rubric
from playbook.evals.scenarios import Scenario, ScenarioSet
from playbook.ingest import Procedure, ingest_procedure, load_procedure
from playbook.ingest.parser import procedure_slug, write_procedure


@dataclass
class Workspace:
    """Where a procedure's inputs live, the store its versions, runs and reports go to, and the
    local directory (`<runs_dir>/<slug>`) that keeps the ingested procedure and the run artifacts."""

    procedure_dir: Path
    runs_dir: Path
    store: RunStore | None = None

    def __post_init__(self) -> None:
        if self.store is None:
            self.store = LocalRunStore(self.runs_dir)

    @cached_property
    def slug(self) -> str:
        return procedure_slug(self.procedure_dir)

    def procedure(self) -> Procedure:
        cached = self.out_dir / "procedure.json"
        return load_procedure(cached) if cached.exists() else ingest_procedure(self.procedure_dir)

    def ingest(self) -> tuple[Procedure, Path]:
        proc = ingest_procedure(self.procedure_dir)
        return proc, write_procedure(proc, self.out_dir / "procedure.json")

    @property
    def out_dir(self) -> Path:
        return self.runs_dir / self.slug

    @property
    def artifacts_dir(self) -> Path:
        return self.out_dir / "artifacts"

    def rubric(self) -> Rubric:
        return Rubric.load(self.procedure_dir / "rubric.yaml")

    def scenarios(self) -> ScenarioSet:
        return ScenarioSet.load(self.procedure_dir / "scenarios.yaml")

    def kb(self) -> KnowledgeBase:
        return KnowledgeBase.from_file(self.procedure_dir / "kb.json")

    def prompt(self, version: int | None = None) -> PromptSpec:
        """A stored prompt version; with no version the latest, creating v1 when none exists."""
        assert self.store is not None
        if version is not None:
            return self.store.load_prompt(self.slug, version)
        versions = self.store.prompt_versions(self.slug)
        if versions:
            return self.store.load_prompt(self.slug, versions[-1])
        spec = PromptSpec(procedure_slug=self.slug)
        self.store.save_prompt(spec)
        return spec

    def report(self, version: int) -> VersionReport:
        assert self.store is not None
        return self.store.load_report(self.slug, version)

    def report_versions(self) -> list[int]:
        assert self.store is not None
        return self.store.report_versions(self.slug)

    def bank(self) -> ScenarioBank:
        assert self.store is not None
        return self.store.load_bank(self.slug)


class Runner:
    def __init__(
        self,
        settings: Settings,
        ws: Workspace,
        *,
        judge: Judge | None = None,
        client: Any | None = None,
        log=None,
    ):
        assert ws.store is not None
        self.settings = settings
        self.ws = ws
        self.store: RunStore = ws.store
        self.client = client or make_client(settings)
        self.judge = judge or (LiveJudge(self.client, settings.model) if settings.live else OfflineJudge())
        self.procedure = ws.procedure()
        self.rubric = ws.rubric()
        self.executor = ToolExecutor(settings, ws.kb())
        self.log = log or (lambda msg: None)
        self.traces: list[RunTrace] = []

    def close(self) -> None:
        """Release the HTTP client the tool executor holds."""
        self.executor.close()

    def reset_fakes(self) -> None:
        """Clear the fake Jira and Slack inboxes between versions (offline mode only)."""
        if self.settings.live:
            return
        for base in (self.settings.jira_base_url, self.settings.slack_base_url):
            try:
                httpx.delete(base + "/_inbox", timeout=5.0)
            except httpx.HTTPError:
                pass

    def run_scenario(self, spec: PromptSpec, scenario: Scenario) -> RunTrace:
        trace = run_agent(
            self.settings,
            spec.render(self.procedure),
            scenario.render(),
            self.executor,
            procedure_slug=self.procedure.slug,
            prompt_version=spec.version,
            scenario_id=scenario.id,
            client=self.client,
        )
        self.store.save_run(trace)
        self.traces.append(trace)
        return trace

    def grade(self, trace: RunTrace, scenario: Scenario) -> RunGrade:
        """Grade a trace and store the grade next to it."""
        grade = Grader(self.rubric, self.judge).grade(trace, scenario)
        self.store.save_grade(grade)
        return grade

    def run_version(self, spec: PromptSpec, scenarios: ScenarioSet | None = None) -> VersionReport:
        scenarios = scenarios or self.ws.scenarios()
        grades: list[RunGrade] = []
        for sc in scenarios.scenarios:
            trace = self.run_scenario(spec, sc)
            grade = self.grade(trace, sc)
            grades.append(grade)
            self.log(
                f"  {spec.label} {sc.id}: {'pass' if grade.passed else 'FAIL'} "
                f"score={grade.score:.2f} calls={len(trace.tool_calls)}"
            )
        report = build_report(grades, self.rubric)
        self.store.save_report(report)
        return report

    def regrade_version(self, version: int) -> VersionReport:
        """Grade stored traces for a version without re-running the agent."""
        scenarios = self.ws.scenarios()
        traces = self.store.list_runs(self.procedure.slug, version)
        self.traces.extend(traces)
        grades = [self.grade(t, scenarios.get(t.scenario_id)) for t in traces]
        report = build_report(grades, self.rubric)
        self.store.save_report(report)
        return report
