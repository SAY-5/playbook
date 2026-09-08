/* Console self-check: reproduces the README numbers from the browser port.
   Expected (offline): support triage 16 scenarios 12.5% -> 87.5% -> 100% with 12 corrections;
   incident communications 8 scenarios 12.5% -> 100%. */
import type { ProcedureFixture } from "../fixtures";
import { runLoop } from "./feedback";
import { pct, formatTable } from "./report";
import { openWorkspace, Runner } from "./runner";

export interface SelfCheckResult {
  ok: boolean;
  lines: string[];
}

interface Expectation {
  dir: string;
  passRates: number[];
  corrections: number;
}

const EXPECTED: Expectation[] = [
  { dir: "support_triage", passRates: [0.125, 0.875, 1], corrections: 12 },
  { dir: "incident_comms", passRates: [0.125, 1], corrections: 6 },
];

export function selfCheck(fixtures: ProcedureFixture[]): SelfCheckResult {
  const lines: string[] = [];
  let ok = true;
  for (const exp of EXPECTED) {
    const fixture = fixtures.find((f) => f.dir === exp.dir);
    if (!fixture) {
      lines.push(`missing fixture ${exp.dir}`);
      ok = false;
      continue;
    }
    const runner = new Runner(openWorkspace(fixture));
    const result = runLoop(runner);
    const rates = result.rounds.map((r) => r.report.passRate);
    const corrections = result.rounds[result.rounds.length - 1].spec.corrections.length;
    lines.push(formatTable(result.rounds.map((r) => r.report)));
    lines.push(`stopped: ${result.stopReason}`);
    for (const c of result.rounds.flatMap((r) => r.corrections)) lines.push(`v${c.version} [${c.stepId}] ${c.text}`);
    const ratesOk = rates.length === exp.passRates.length && rates.every((r, i) => Math.abs(r - exp.passRates[i]) < 1e-9);
    const corrOk = corrections === exp.corrections;
    lines.push(
      `${exp.dir}: pass rates ${rates.map(pct).join(" -> ")} (${ratesOk ? "ok" : "MISMATCH"}), ` +
        `${corrections} corrections (${corrOk ? "ok" : "MISMATCH"}), mode=offline`,
    );
    ok = ok && ratesOk && corrOk;
  }
  lines.push(ok ? "self-check passed" : "self-check FAILED");
  return { ok, lines };
}
