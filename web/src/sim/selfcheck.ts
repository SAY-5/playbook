/* Console self-check for the browser port. Every expectation below is quoted from the measured
   results in the repository README, so a drift in the ported rule engine, grader or correction
   derivation fails here instead of silently changing the page. */
import type { ProcedureFixture } from "../fixtures";
import { PCT_CASES } from "../fixtures/pct-cases";
import { arcDigest, arcRunIds, computeArc, type Arc } from "./arc";
import { pct } from "./report";
import type { RunTrace } from "./types";

export interface Assertion {
  name: string;
  ok: boolean;
  detail: string;
}

export interface SelfCheckResult {
  ok: boolean;
  assertions: Assertion[];
  passed: number;
  total: number;
  lines: string[];
}

export interface SourceFile {
  name: string;
  text: string;
}

/** The tool names the ported executor is allowed to produce. */
const TOOL_NAMES = ["kb.search", "jira.create_issue", "jira.transition", "jira.comment", "slack.post", "slack.lookup_channel"];

class Checks {
  readonly items: Assertion[] = [];

  is(name: string, actual: unknown, expected: unknown): void {
    const a = JSON.stringify(actual);
    const e = JSON.stringify(expected);
    this.items.push({ name, ok: a === e, detail: a === e ? a : `${a} != ${e}` });
  }

  ok(name: string, condition: boolean, detail: string): void {
    this.items.push({ name, ok: condition, detail });
  }
}

const rates = (arc: Arc): string => arc.passRates.map(pct).join(" -> ");
const means = (arc: Arc): string => arc.meanScores.map(pct).join(" -> ");
const criterion = (arc: Arc, id: string): string => arc.rounds.map((r) => pct(r.report.perCriterion[id] ?? 0)).join(" -> ");
const correctionLines = (arc: Arc): string[] => arc.corrections.map((c) => `v${c.version} [${c.stepId}] ${c.text}`);

function checkTriage(c: Checks, arc: Arc): void {
  c.is("support triage: slug", arc.slug, "support-triage");
  c.is("support triage: scenario count", arc.scenarios, 16);
  c.is("support triage: prompt versions", arc.rounds.map((r) => r.spec.version), [1, 2, 3]);
  c.is("support triage: pass rate arc (README)", rates(arc), "12.5% -> 87.5% -> 100.0%");
  c.is("support triage: mean score arc (README)", means(arc), "80.1% -> 98.9% -> 100.0%");
  c.is("support triage: forbidden actions (README)", arc.forbidden, [2, 2, 0]);
  c.is("support triage: correction count (README)", arc.corrections.length, 12);
  c.is("support triage: stop reason", arc.stopReason, "all scenarios pass");
  c.is(
    "support triage: required-action coverage",
    arc.rounds.map((r) => pct(r.report.requiredActionCoverage)).join(" -> "),
    "100.0% -> 100.0% -> 100.0%",
  );
  c.is("support triage: priority_matches_matrix (README)", criterion(arc, "priority_matches_matrix"), "12.5% -> 100.0% -> 100.0%");
  c.is("support triage: escalated_when_required (README)", criterion(arc, "escalated_when_required"), "43.8% -> 100.0% -> 100.0%");
  c.is("support triage: no_pii_in_slack (README)", criterion(arc, "no_pii_in_slack"), "87.5% -> 87.5% -> 100.0%");
  c.is("support triage: summary_prefixed (README)", criterion(arc, "summary_prefixed"), "0.0% -> 100.0% -> 100.0%");
  c.ok(
    "support triage: table reproduces the README pass-rate row",
    arc.table.includes("| pass rate                 | 12.5%  | 87.5%  | 100.0% | +87.5%         |"),
    "pass-rate row",
  );
  const lines = correctionLines(arc);
  c.is("support triage: first correction (README)", lines[0], 'v2 [create-ticket] Set summary to "[{severity}] {title}".');
  c.is(
    "support triage: last correction is the v3 phone-number rule (README)",
    lines[lines.length - 1],
    "v3 [escalate] When posting to Slack, do not include the customer phone number.",
  );
  c.is(
    "support triage: corrections per version",
    [lines.filter((l) => l.startsWith("v2")).length, lines.filter((l) => l.startsWith("v3")).length],
    [11, 1],
  );
  c.ok(
    "support triage: every scenario passes in the last round",
    arc.rounds[arc.rounds.length - 1].report.grades.every((g) => g.passed),
    `${arc.rounds[arc.rounds.length - 1].report.passed}/${arc.scenarios}`,
  );
  c.is("support triage: no scenario regresses between rounds", arc.rounds.map((r) => r.comparison?.newlyFailing.length ?? 0), [0, 0, 0]);
}

function checkIncident(c: Checks, arc: Arc): void {
  c.is("incident comms: slug", arc.slug, "incident-communications");
  c.is("incident comms: scenario count", arc.scenarios, 8);
  c.is("incident comms: pass rate arc (README)", rates(arc), "12.5% -> 100.0%");
  c.is("incident comms: mean score arc (README)", means(arc), "83.3% -> 100.0%");
  c.is("incident comms: correction count", arc.corrections.length, 6);
  c.is("incident comms: forbidden actions (README)", arc.forbidden, [0, 0]);
  c.is("incident comms: stop reason", arc.stopReason, "all scenarios pass");
  c.is(
    "incident comms: status_updates_when_customer_facing (README)",
    criterion(arc, "status_updates_when_customer_facing"),
    "50.0% -> 100.0%",
  );
  c.is("incident comms: ic_paged_for_full_outage (README)", criterion(arc, "ic_paged_for_full_outage"), "75.0% -> 100.0%");
  c.ok(
    "incident comms: table reproduces the README pass-rate row",
    arc.table.includes("| pass rate                             | 12.5%  | 100.0% | +87.5%         |"),
    "pass-rate row",
  );
  c.is("incident comms: first correction", correctionLines(arc)[0], 'v2 [open-incident] Set summary to "[{impact}] {title}".');
}

function checkTraces(c: Checks, arc: Arc): void {
  const traces: RunTrace[] = arc.rounds.flatMap((r) => r.outcomes.map((o) => o.trace));
  c.ok("traces: every run completed", traces.every((t) => t.status === "completed"), `${traces.length} runs`);
  c.ok(
    "traces: every run made tool calls",
    traces.every((t) => t.toolCalls.length > 0),
    `min ${Math.min(...traces.map((t) => t.toolCalls.length))} calls`,
  );
  c.ok(
    "traces: only registered tools are called",
    traces.every((t) => t.toolCalls.every((call) => TOOL_NAMES.includes(call.name))),
    TOOL_NAMES.join(", "),
  );
  c.ok("traces: no tool call errored", traces.every((t) => t.toolCalls.every((call) => call.error === null)), "0 errors");
  c.ok("traces: every run ends with a summary line", traces.every((t) => t.finalText.trim().length > 0), "non-empty final text");
  c.ok(
    "traces: the system prompt carries its version's corrections",
    arc.rounds.every((r) => r.outcomes.every((o) => r.spec.corrections.every((corr) => o.trace.systemPrompt.includes(corr.text)))),
    "all corrections present",
  );
}

function checkDeterminism(c: Checks, fixtures: ProcedureFixture[]): void {
  for (const fixture of fixtures) {
    const first = computeArc(fixture);
    const again = computeArc(fixture);
    c.ok(`${fixture.dir}: same seed gives an identical summary`, first.summary === again.summary, "summary block");
    c.ok(`${fixture.dir}: same seed gives an identical digest`, arcDigest(first) === arcDigest(again), "tables, log, grades");
    c.ok(`${fixture.dir}: same seed gives identical run ids`, arcRunIds(first).join() === arcRunIds(again).join(), "run ids");
    const other = computeArc(fixture, (first.seed ^ 0x5bf03635) >>> 0);
    const withoutSeedLine = (s: string) => s.split("\n").slice(0, -1).join("\n");
    c.ok(
      `${fixture.dir}: a different seed moves the ids but not the result`,
      arcRunIds(other).join() !== arcRunIds(first).join() && withoutSeedLine(other.summary) === withoutSeedLine(first.summary),
      "ids differ, graded outcome identical",
    );
  }
}

function checkFormatting(c: Checks): void {
  const wrong = PCT_CASES.filter(([v, expected]) => pct(v) !== expected).map(([v, expected]) => `${v}: ${pct(v)} != ${expected}`);
  c.ok(
    `percent formatting matches Python on ${PCT_CASES.length} values`,
    wrong.length === 0,
    wrong.length ? wrong.join(", ") : `${PCT_CASES.length} values, ties included`,
  );
}

const BANNED: [string, RegExp][] = [
  ["Math.random", /Math\.random/],
  ["wall-clock time", /Date\.now|new Date\(/],
  ["eval", /\beval\(/],
];

function checkPurity(c: Checks, sources: SourceFile[]): void {
  for (const [label, re] of BANNED) {
    const hits = sources.filter((s) => re.test(s.text)).map((s) => s.name);
    c.ok(`simulation is free of ${label}`, hits.length === 0, hits.length ? hits.join(", ") : `${sources.length} modules clean`);
  }
}

export function selfCheck(fixtures: ProcedureFixture[], sources: SourceFile[] = []): SelfCheckResult {
  const c = new Checks();
  const lines: string[] = [];

  const triage = fixtures.find((f) => f.dir === "support_triage");
  const incident = fixtures.find((f) => f.dir === "incident_comms");
  if (!triage || !incident) {
    const missing: Assertion = { name: "both procedure fixtures present", ok: false, detail: "missing fixture" };
    return { ok: false, assertions: [missing], passed: 0, total: 1, lines };
  }

  const triageArc = computeArc(triage);
  const incidentArc = computeArc(incident);
  for (const arc of [triageArc, incidentArc]) {
    lines.push(arc.table);
    lines.push(`stopped: ${arc.stopReason}`);
    for (const line of correctionLines(arc)) lines.push(line);
    lines.push("");
    lines.push(arc.summary);
    lines.push("");
  }

  checkTriage(c, triageArc);
  checkIncident(c, incidentArc);
  checkTraces(c, triageArc);
  checkDeterminism(c, [triage, incident]);
  checkFormatting(c);
  if (sources.length) checkPurity(c, sources);

  const passed = c.items.filter((a) => a.ok).length;
  for (const a of c.items) lines.push(`${a.ok ? "ok  " : "FAIL"} ${a.name}: ${a.detail}`);
  const ok = passed === c.items.length;
  lines.push(`${passed}/${c.items.length} assertions passed`);
  lines.push(ok ? "self-check passed" : "self-check FAILED");
  return { ok, assertions: c.items, passed, total: c.items.length, lines };
}
