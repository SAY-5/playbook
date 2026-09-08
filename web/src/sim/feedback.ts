/* Port of playbook/feedback/loop.py: run, grade, correct, re-run until the pass rate plateaus. */
import { deriveCorrections } from "./corrections";
import { initialSpec, specLabel, withCorrections } from "./prompt";
import { compareReports } from "./report";
import type { RunOutcome, Runner } from "./runner";
import type { Comparison, Correction, PromptSpec, VersionReport } from "./types";

export interface Round {
  spec: PromptSpec;
  report: VersionReport;
  outcomes: RunOutcome[];
  corrections: Correction[];
  comparison: Comparison | null;
}

export interface LoopResult {
  rounds: Round[];
  stopReason: string;
}

/** Create the next prompt version from this report's failures, or null if nothing applies. */
export function improveOnce(runner: Runner, spec: PromptSpec, report: VersionReport): PromptSpec | null {
  const corrections = deriveCorrections(report.grades, runner.ws.scenarios, runner.ws.rubric, spec.version);
  if (!corrections.length) return null;
  const next = withCorrections(
    spec,
    corrections,
    `${corrections.length} correction(s) from ${specLabel(spec)} failures (pass rate ${Math.round(report.passRate * 100)}%)`,
  );
  if (next.corrections.length === spec.corrections.length) return null;
  return next;
}

export function runRound(runner: Runner, spec: PromptSpec, previous: Round | null): Round {
  runner.resetFakes();
  runner.log(`running ${specLabel(spec)}`);
  const { report, outcomes } = runner.runVersion(spec);
  const added = spec.corrections.filter((c) => c.version === spec.version);
  return {
    spec,
    report,
    outcomes,
    corrections: previous ? added : [],
    comparison: previous ? compareReports(previous.report, report) : null,
  };
}

export function runLoop(runner: Runner, start = initialSpec(runner.ws.procedure.slug), maxRounds = 5, minDelta = 0): LoopResult {
  let round = runRound(runner, start, null);
  const rounds = [round];
  let reason = "max rounds reached";
  for (let i = 0; i < maxRounds; i++) {
    if (round.report.passRate >= 1) {
      reason = "all scenarios pass";
      break;
    }
    const next = improveOnce(runner, round.spec, round.report);
    if (!next) {
      reason = "no applicable corrections for the remaining failures";
      break;
    }
    const nextRound = runRound(runner, next, round);
    rounds.push(nextRound);
    round = nextRound;
    if ((nextRound.comparison?.passRateDelta ?? 0) <= minDelta) {
      reason = `pass rate plateaued at ${Math.round(round.report.passRate * 100)}%`;
      break;
    }
  }
  if (rounds.length && round.report.passRate >= 1 && reason === "max rounds reached") reason = "all scenarios pass";
  return { rounds, stopReason: reason };
}
