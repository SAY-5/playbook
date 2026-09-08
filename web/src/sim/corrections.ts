/* Port of playbook/feedback/corrections.py: derive explicit prompt corrections from graded failures.

   For each failed criterion that carries a remediation, the failing scenarios are grouped and the
   smallest set of scenario facts that separates them from scenarios with a different expectation is
   turned into a condition, for example `severity is sev2 and tier is enterprise`. */
import { getScenario, scenarioFacts } from "./scenarios";
import type { Correction, CriterionResult, JsonValue, Rubric, RunGrade, Scenario, ScenarioSet } from "./types";

type Fact = string | boolean | undefined;

export function condText(variable: string, value: Fact): string {
  if (variable === "customer_facing") {
    const truthy = ["yes", "true", "1"].includes(String(value).toLowerCase());
    return truthy ? "the incident is customer-facing" : "the incident is not customer-facing";
  }
  if (variable === "kb_hit") return value ? "a KB match is found" : "no KB match is found";
  return `${variable} is ${String(value)}`;
}

function pyStr(v: JsonValue | undefined): string {
  if (v === null || v === undefined) return "None";
  if (typeof v === "boolean") return v ? "True" : "False";
  return String(v);
}

function fill(rule: string, cond: string, values: Record<string, JsonValue | undefined>): string {
  let text = rule;
  if (cond) {
    text = text.split("<cond>").join(cond);
  } else {
    text = text.replace(/^When <cond>, (\w)/, (_m, ch: string) => ch.toUpperCase());
    text = text.split(" when <cond>").join("").split("<cond>").join("");
  }
  for (const [k, v] of Object.entries(values)) text = text.split(`<${k}>`).join(pyStr(v));
  return text;
}

function* combinations<T>(items: T[], size: number, start = 0, prefix: T[] = []): Generator<T[]> {
  if (prefix.length === size) {
    yield prefix;
    return;
  }
  for (let i = start; i < items.length; i++) yield* combinations(items, size, i + 1, [...prefix, items[i]]);
}

function sameExpectation(a: JsonValue | undefined, b: JsonValue | undefined): boolean {
  return (a ?? null) === (b ?? null);
}

/** Smallest subset of condVars whose values on `target` never coincide with a scenario that expects
    something different. Falls back to all vars. */
export function discriminate(
  target: Scenario,
  targetExpected: JsonValue | undefined,
  others: [Scenario, JsonValue | undefined][],
  condVars: string[],
): string {
  if (!condVars.length) return "";
  const tf = scenarioFacts(target);
  const key = (facts: Record<string, Fact>, subset: string[]) => JSON.stringify(subset.map((v) => facts[v] ?? null));
  for (let size = 1; size <= condVars.length; size++) {
    for (const subset of combinations(condVars, size)) {
      const mine = key(tf, subset);
      const clash = others.some(([o, exp]) => key(scenarioFacts(o), subset) === mine && !sameExpectation(exp, targetExpected));
      if (!clash) return subset.map((v) => condText(v, tf[v])).join(" and ");
    }
  }
  return condVars.map((v) => condText(v, tf[v])).join(" and ");
}

export function deriveCorrections(grades: RunGrade[], scenarios: ScenarioSet, rubric: Rubric, version: number): Correction[] {
  const out: Correction[] = [];
  const seen = new Set<string>();
  for (const crit of rubric.criteria) {
    const rem = crit.remediation;
    if (!rem) continue;
    const rows: [Scenario, CriterionResult][] = [];
    for (const g of grades) {
      const res = g.results.find((r) => r.id === crit.id);
      if (res) rows.push([getScenario(scenarios, g.scenarioId), res]);
    }
    const failures = rows.filter(
      ([, res]) => !res.passed && (rem.onlyWhenExpected === null || (res.evidence.expected ?? null) === rem.onlyWhenExpected),
    );
    if (!failures.length) continue;
    const others: [Scenario, JsonValue | undefined][] = rows.map(([sc, res]) => [sc, res.evidence.expected]);
    const placeholders = Array.from(rem.rule.matchAll(/<(\w+)>/g), (m) => m[1]).filter((p) => p !== "cond");
    const textFor = (sc: Scenario, res: CriterionResult): string => {
      const values: Record<string, JsonValue | undefined> = {};
      for (const p of placeholders) if (p in res.evidence) values[p] = res.evidence[p];
      const cond = discriminate(sc, res.evidence.expected, others, rem.condVars);
      return fill(rem.rule, cond, values);
    };
    for (const [sc, res] of failures) {
      const text = textFor(sc, res);
      const dedupKey = `${rem.step} ${text}`;
      if (seen.has(dedupKey)) continue;
      seen.add(dedupKey);
      const supporting = failures.filter(([s, r]) => textFor(s, r) === text).map(([s]) => s.id);
      out.push({
        stepId: rem.step,
        text,
        criterion: crit.id,
        version: version + 1,
        evidence:
          `failed in v${version} on ${supporting.slice(0, 4).join(", ")}` +
          (supporting.length > 4 ? ` and ${supporting.length - 4} more` : ""),
      });
    }
  }
  return out;
}
