/* Port of playbook/runner.py: ties ingest, prompt, agent loop, fakes and grader together for one procedure. */
import type { ProcedureFixture } from "../fixtures";
import { RuleEngine } from "./engine";
import { gradeRun } from "./grader";
import { ingestProcedure } from "./ingest";
import { runAgent } from "./loop";
import { Prng, seedFrom } from "./prng";
import { renderPrompt, specLabel } from "./prompt";
import { buildReport } from "./report";
import { loadRubric, loadScenarios, renderScenario } from "./scenarios";
import { FakeJira, FakeSlack, KnowledgeBase, ToolExecutor } from "./tools";
import type { Procedure, PromptSpec, Rubric, RunGrade, RunTrace, Scenario, ScenarioSet, VersionReport } from "./types";

export interface RunOutcome {
  trace: RunTrace;
  grade: RunGrade;
}

export interface Workspace {
  fixture: ProcedureFixture;
  procedure: Procedure;
  rubric: Rubric;
  scenarios: ScenarioSet;
  kb: KnowledgeBase;
}

export function openWorkspace(fixture: ProcedureFixture): Workspace {
  return {
    fixture,
    procedure: ingestProcedure(fixture.sop, fixture.walkthrough),
    rubric: loadRubric(fixture.rubricYaml),
    scenarios: loadScenarios(fixture.scenariosYaml),
    kb: new KnowledgeBase(fixture.kb),
  };
}

/** One procedure's fakes, engine and grader. Deterministic: same inputs, same traces. */
export class Runner {
  readonly jira = new FakeJira();
  readonly slack = new FakeSlack();
  readonly executor: ToolExecutor;
  readonly engine: RuleEngine;
  private prng: Prng;
  log: (msg: string) => void = () => undefined;

  constructor(
    public ws: Workspace,
    seed = seedFrom(ws.procedure.slug),
  ) {
    this.executor = new ToolExecutor(ws.kb, this.jira, this.slack);
    this.prng = new Prng(seed);
    this.engine = new RuleEngine(this.prng);
  }

  /** Clear the fake Jira and Slack inboxes between versions. */
  resetFakes(): void {
    this.jira.reset();
    this.slack.reset();
  }

  systemPrompt(spec: PromptSpec): string {
    return renderPrompt(spec, this.ws.procedure);
  }

  runScenario(spec: PromptSpec, scenario: Scenario): RunTrace {
    return runAgent(this.engine, this.prng, this.systemPrompt(spec), renderScenario(scenario), this.executor, {
      procedureSlug: this.ws.procedure.slug,
      promptVersion: spec.version,
      scenarioId: scenario.id,
    });
  }

  grade(trace: RunTrace, scenario: Scenario): RunGrade {
    return gradeRun(this.ws.rubric, trace, scenario);
  }

  runAndGrade(spec: PromptSpec, scenario: Scenario): RunOutcome {
    const trace = this.runScenario(spec, scenario);
    return { trace, grade: this.grade(trace, scenario) };
  }

  runVersion(spec: PromptSpec, onRun?: (outcome: RunOutcome) => void): { report: VersionReport; outcomes: RunOutcome[] } {
    const outcomes: RunOutcome[] = [];
    for (const sc of this.ws.scenarios.scenarios) {
      const outcome = this.runAndGrade(spec, sc);
      outcomes.push(outcome);
      onRun?.(outcome);
      this.log(
        `  ${specLabel(spec)} ${sc.id}: ${outcome.grade.passed ? "pass" : "FAIL"} ` +
          `score=${outcome.grade.score.toFixed(2)} calls=${outcome.trace.toolCalls.length}`,
      );
    }
    const report = buildReport(
      outcomes.map((o) => o.grade),
      this.ws.rubric,
    );
    return { report, outcomes };
  }
}
