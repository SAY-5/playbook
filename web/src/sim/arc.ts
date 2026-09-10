/* The whole offline arc for one procedure in a single value: every prompt version, its report,
   the corrections that produced the next version, the log the CLI prints and a summary block.
   Deterministic for a given seed, so the browser, the node self-check and the Python CLI agree. */
import type { ProcedureFixture } from "../fixtures";
import { runLoop, type Round } from "./feedback";
import { seedFrom } from "./prng";
import { formatTable, pct } from "./report";
import { openWorkspace, Runner, type Workspace } from "./runner";
import type { Correction, RunTrace } from "./types";

export interface Arc {
  dir: string;
  label: string;
  slug: string;
  seed: number;
  scenarios: number;
  rounds: Round[];
  stopReason: string;
  log: string[];
  table: string;
  corrections: Correction[];
  passRates: number[];
  meanScores: number[];
  forbidden: number[];
  toolCalls: number;
  summary: string;
  workspace: Workspace;
}

const hex8 = (n: number): string => `0x${(n >>> 0).toString(16).padStart(8, "0")}`;

function summarise(arc: Omit<Arc, "summary">): string {
  const rows: [string, string][] = [
    ["procedure", arc.slug],
    ["scenarios", String(arc.scenarios)],
    ["versions", arc.rounds.map((r) => `v${r.spec.version}`).join(" -> ")],
    ["pass rate", arc.passRates.map(pct).join(" -> ")],
    ["mean score", arc.meanScores.map(pct).join(" -> ")],
    ["forbidden actions", arc.forbidden.join(" -> ")],
    ["corrections", String(arc.corrections.length)],
    ["tool calls", String(arc.toolCalls)],
    ["stopped", arc.stopReason],
    ["mode", `offline stand-in, seed ${hex8(arc.seed)}`],
  ];
  const width = Math.max(...rows.map(([k]) => k.length));
  return rows.map(([k, v]) => `${k.padEnd(width)}  ${v}`).join("\n");
}

/** Run the feedback loop end to end and collect everything the sections need. */
export function computeArc(fixture: ProcedureFixture, seed?: number): Arc {
  const workspace = openWorkspace(fixture);
  const usedSeed = seed ?? seedFrom(workspace.procedure.slug);
  const runner = new Runner(workspace, usedSeed);
  const log: string[] = [];
  runner.log = (msg) => log.push(msg);

  const result = runLoop(runner);
  const rounds = result.rounds;
  const partial: Omit<Arc, "summary"> = {
    dir: fixture.dir,
    label: fixture.label,
    slug: workspace.procedure.slug,
    seed: usedSeed,
    scenarios: workspace.scenarios.scenarios.length,
    rounds,
    stopReason: result.stopReason,
    log,
    table: formatTable(rounds.map((r) => r.report)),
    corrections: rounds[rounds.length - 1].spec.corrections,
    passRates: rounds.map((r) => r.report.passRate),
    meanScores: rounds.map((r) => r.report.meanScore),
    forbidden: rounds.map((r) => r.report.forbiddenViolations),
    toolCalls: rounds.reduce((s, r) => s + r.outcomes.reduce((t, o) => t + o.trace.toolCalls.length, 0), 0),
    workspace,
  };
  return { ...partial, summary: summarise(partial) };
}

/** Every scenario id, in the order the rubric evaluates them. */
export function scenarioIds(arc: Arc): string[] {
  return arc.workspace.scenarios.scenarios.map((s) => s.id);
}

/** The pass or fail state of one scenario in one round. */
export function verdict(arc: Arc, roundIndex: number, scenarioId: string): boolean | null {
  const grade = arc.rounds[roundIndex]?.report.grades.find((g) => g.scenarioId === scenarioId);
  return grade ? grade.passed : null;
}

export function traceFor(arc: Arc, roundIndex: number, scenarioId: string): RunTrace | null {
  const outcome = arc.rounds[roundIndex]?.outcomes.find((o) => o.trace.scenarioId === scenarioId);
  return outcome ? outcome.trace : null;
}

/** Stable fingerprint of everything a reader can see, for the determinism check. */
export function arcDigest(arc: Arc): string {
  return JSON.stringify({
    slug: arc.slug,
    scenarios: arc.scenarios,
    stopReason: arc.stopReason,
    passRates: arc.passRates,
    meanScores: arc.meanScores,
    forbidden: arc.forbidden,
    table: arc.table,
    summary: arc.summary,
    log: arc.log,
    corrections: arc.corrections.map((c) => `v${c.version} [${c.stepId}] ${c.text}`),
    grades: arc.rounds.map((r) => r.report.grades.map((g) => `${g.scenarioId}:${g.passed ? 1 : 0}:${g.score}`)),
  });
}

/** Run ids and simulated latencies come from the seed; the graded outcome must not. */
export function arcRunIds(arc: Arc): string[] {
  return arc.rounds.flatMap((r) => r.outcomes.map((o) => o.trace.runId));
}
