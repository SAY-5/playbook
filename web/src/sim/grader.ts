/* Port of playbook/evals/grader.py and the offline judge from playbook/evals/judge.py. */
import { EMAIL_RE, PHONE_RE } from "./engine";
import { callsNamed, toolNames } from "./loop";
import { requiredActions } from "./scenarios";
import type { Criterion, CriterionResult, JsonValue, Rubric, RunGrade, RunTrace, Scenario } from "./types";

type Check = [boolean, number, Record<string, JsonValue>, string];

function issueKey(trace: RunTrace): string | null {
  for (const c of callsNamed(trace, "jira.create_issue")) {
    if (c.result && c.result.issue_key) return String(c.result.issue_key);
  }
  return null;
}

function serviceChannel(trace: RunTrace): string | null {
  for (const c of callsNamed(trace, "slack.lookup_channel")) {
    if (c.result && c.result.channel) return String(c.result.channel);
  }
  return null;
}

function expectedValue(scenario: Scenario, crit: Criterion): JsonValue {
  const key = crit.params.equals_expected;
  if (key !== undefined) {
    const v = scenario.expected[String(key)];
    return v === undefined ? null : v;
  }
  const eq = crit.params.equals;
  return eq === undefined ? null : eq;
}

function repr(v: JsonValue | undefined): string {
  if (v === null || v === undefined) return "None";
  if (typeof v === "string") return `'${v}'`;
  if (typeof v === "boolean") return v ? "True" : "False";
  return String(v);
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Rule-based stand-in for the model judge: completed run, error-free tools, summary names the ticket. */
export function offlineJudge(trace: RunTrace): [number, string] {
  const notes: string[] = [];
  let score = 0;
  if (trace.status === "completed") {
    score += 0.4;
    notes.push("run completed within the step budget");
  } else {
    notes.push(`run ended with status ${trace.status}`);
  }
  const errors = trace.toolCalls.filter((c) => c.error);
  if (trace.toolCalls.length && !errors.length) {
    score += 0.3;
    notes.push("no tool errors");
  } else if (errors.length) {
    notes.push(`${errors.length} tool call(s) failed`);
  }
  const keys = callsNamed(trace, "jira.create_issue")
    .filter((c) => c.result)
    .map((c) => String(c.result!.issue_key ?? ""));
  if (keys.length && keys[0] && trace.finalText.includes(keys[0])) {
    score += 0.3;
    notes.push(`final summary names ${keys[0]}`);
  } else {
    notes.push("final summary does not name the ticket");
  }
  return [Math.round(score * 1000) / 1000, notes.join("; ")];
}

const CHECKS: Record<Criterion["kind"], (crit: Criterion, trace: RunTrace, sc: Scenario) => Check> = {
  tool_called(crit, trace) {
    const tool = String(crit.params.tool);
    const ok = trace.toolCalls.some((c) => c.name === tool && !c.error);
    return [ok, ok ? 1 : 0, { tool }, `${tool} ${ok ? "called" : "not called"}`];
  },
  tool_order(crit, trace) {
    const names = toolNames(trace);
    const before = String(crit.params.before);
    const after = String(crit.params.after);
    if (!names.includes(before) || !names.includes(after)) {
      const missing = [before, after].filter((t) => !names.includes(t));
      return [false, 0, { missing }, `missing ${missing.join(", ")}`];
    }
    const ok = names.indexOf(before) < names.indexOf(after);
    return [ok, ok ? 1 : 0, { order: names }, `${before} ${ok ? "before" : "after"} ${after}`];
  },
  issue_field(crit, trace, sc) {
    const tool = String(crit.params.tool ?? "jira.create_issue");
    const fld = String(crit.params.field);
    const calls = callsNamed(trace, tool);
    if (!calls.length) return [false, 0, { observed: null }, `no ${tool} call`];
    const observedRaw = calls[0].args[fld];
    const observed: JsonValue = observedRaw === undefined ? null : observedRaw;
    if (crit.params.matches !== undefined) {
      const vars: Record<string, string> = {};
      for (const [k, v] of Object.entries(sc.intake)) vars[k] = escapeRegex(String(v));
      for (const [k, v] of Object.entries(sc.expected)) vars[k] = escapeRegex(String(v));
      const pattern = String(crit.params.matches).replace(/\{(\w+)\}/g, (w, k: string) => (k in vars ? vars[k] : w));
      const ok = Boolean(observed) && new RegExp(pattern).test(String(observed));
      return [ok, ok ? 1 : 0, { observed, pattern }, `${fld}=${repr(observed)}`];
    }
    const expected = expectedValue(sc, crit);
    const ok = observed === expected;
    return [ok, ok ? 1 : 0, { observed, expected }, `${fld}=${repr(observed)}, expected ${repr(expected)}`];
  },
  slack_post(crit, trace, sc) {
    let channel = String(crit.params.channel);
    if (channel === "service_channel") channel = serviceChannel(trace) ?? "#unknown";
    const when = crit.params.when_expected;
    const required = when !== undefined ? Boolean(sc.expected[String(when)] ?? true) : true;
    const posts = callsNamed(trace, "slack.post").filter((c) => c.args.channel === channel && !c.error);
    if (!required) {
      const ok = !posts.length;
      const ev = { expected: false, reason: posts.length ? "unexpected" : "absent" };
      return [ok, ok ? 1 : 0, ev, `post to ${channel} ${ok ? "not expected" : "made but not expected"}`];
    }
    if (!posts.length) return [false, 0, { expected: true, reason: "missing" }, `no post to ${channel}`];
    if (crit.params.mention_issue_key) {
      const key = issueKey(trace);
      if (!key || !posts.some((c) => String(c.args.text ?? "").includes(key))) {
        return [false, 0.5, { expected: true, reason: "no_key" }, `post to ${channel} lacks issue key`];
      }
    }
    return [true, 1, { expected: true, reason: "ok" }, `post to ${channel} ok`];
  },
  transition(crit, trace, sc) {
    const calls = callsNamed(trace, "jira.transition");
    const observedRaw = calls.length ? calls[calls.length - 1].args.status : undefined;
    const observed: JsonValue = observedRaw === undefined ? null : observedRaw;
    const expected = expectedValue(sc, crit);
    const ok = observed === expected;
    return [ok, ok ? 1 : 0, { observed, expected }, `final status ${repr(observed)}, expected ${repr(expected)}`];
  },
  forbidden_transition(crit, trace) {
    const status = String(crit.params.status);
    const hit = callsNamed(trace, "jira.transition").filter((c) => c.args.status === status);
    return [!hit.length, hit.length ? 0 : 1, { count: hit.length }, `${hit.length} transition(s) to ${status}`];
  },
  forbidden_channel(crit, trace) {
    const channel = String(crit.params.channel);
    const hit = callsNamed(trace, "slack.post").filter((c) => c.args.channel === channel);
    return [!hit.length, hit.length ? 0 : 1, { count: hit.length }, `${hit.length} post(s) to ${channel}`];
  },
  no_pii_in_slack(_crit, trace) {
    for (const c of callsNamed(trace, "slack.post")) {
      const text = String(c.args.text ?? "");
      const channel = c.args.channel === undefined ? null : c.args.channel;
      if (EMAIL_RE.test(text)) return [false, 0, { pii_kind: "email", channel }, "email posted to Slack"];
      if (PHONE_RE.test(text)) return [false, 0, { pii_kind: "phone number", channel }, "phone number posted to Slack"];
    }
    return [true, 1, {}, "no PII in Slack posts"];
  },
  text_absent(crit, trace) {
    const phrase = String(crit.params.phrase).toLowerCase();
    const channel = crit.params.channel === undefined ? null : String(crit.params.channel);
    for (const c of callsNamed(trace, "slack.post")) {
      if (channel && c.args.channel !== channel) continue;
      if (String(c.args.text ?? "").toLowerCase().includes(phrase)) {
        return [false, 0, { channel: c.args.channel ?? null }, `'${phrase}' found in post`];
      }
    }
    return [true, 1, {}, `'${phrase}' absent`];
  },
  judge(crit, trace) {
    const [score, rationale] = offlineJudge(trace);
    const threshold = Number(crit.params.pass_at ?? 0.7);
    return [score >= threshold, score, { judge: "offline-heuristic" }, rationale];
  },
};

export function gradeRun(rubric: Rubric, trace: RunTrace, scenario: Scenario): RunGrade {
  const results: CriterionResult[] = rubric.criteria.map((crit) => {
    const [passed, score, evidence, rationale] = CHECKS[crit.kind](crit, trace, scenario);
    return {
      id: crit.id,
      kind: crit.kind,
      passed,
      score: Math.round(score * 1000) / 1000,
      weight: crit.weight,
      forbidden: crit.forbidden,
      evidence,
      rationale,
    };
  });
  const totalW = results.reduce((n, r) => n + r.weight, 0) || 1;
  const score = Math.round((results.reduce((n, r) => n + r.weight * r.score, 0) / totalW) * 10000) / 10000;
  const forbidden = results.filter((r) => r.forbidden && !r.passed).length;
  const required = requiredActions(rubric);
  const made = required.filter((t) => trace.toolCalls.some((c) => c.name === t && !c.error)).length;
  const passed = trace.status === "completed" && forbidden === 0 && score >= rubric.passThreshold;
  return {
    runId: trace.runId,
    scenarioId: scenario.id,
    procedureSlug: trace.procedureSlug,
    promptVersion: trace.promptVersion,
    mode: trace.mode,
    status: trace.status,
    results,
    score,
    passed,
    forbiddenViolations: forbidden,
    requiredActionsMade: made,
    requiredActionsTotal: required.length,
  };
}

export function failedResults(grade: RunGrade): CriterionResult[] {
  return grade.results.filter((r) => !r.passed);
}
