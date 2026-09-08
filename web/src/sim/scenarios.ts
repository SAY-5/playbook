/* Port of playbook/evals/scenarios.py and playbook/evals/rubric.py: YAML scenario sets and rubrics. */
import YAML from "yaml";
import type { Criterion, CriterionKind, Rubric, Scenario, ScenarioSet } from "./types";

const CRITERION_KINDS: CriterionKind[] = [
  "tool_called",
  "tool_order",
  "issue_field",
  "slack_post",
  "transition",
  "forbidden_transition",
  "forbidden_channel",
  "no_pii_in_slack",
  "text_absent",
  "judge",
];

type Raw = Record<string, unknown>;

function asRecord(v: unknown): Raw {
  return v && typeof v === "object" ? (v as Raw) : {};
}

export function loadScenarios(yamlText: string): ScenarioSet {
  const data = asRecord(YAML.parse(yamlText));
  const list = (data.scenarios as Raw[]) ?? [];
  const scenarios: Scenario[] = list.map((s) => {
    const intake: Record<string, string> = {};
    for (const [k, v] of Object.entries(asRecord(s.intake))) intake[k] = String(v);
    const expected: Record<string, string | boolean> = {};
    for (const [k, v] of Object.entries(asRecord(s.expected))) {
      expected[k] = typeof v === "boolean" ? v : String(v);
    }
    return {
      id: String(s.id),
      intake,
      expected,
      tags: ((s.tags as unknown[]) ?? []).map(String),
    };
  });
  const ids = new Set(scenarios.map((s) => s.id));
  if (ids.size !== scenarios.length) throw new Error("duplicate scenario ids");
  return { procedureSlug: String(data.procedure), scenarios };
}

/** Everything a correction condition may refer to. */
export function scenarioFacts(sc: Scenario): Record<string, string | boolean | undefined> {
  const facts: Record<string, string | boolean | undefined> = {};
  for (const [k, v] of Object.entries(sc.intake)) {
    if (k !== "kind" && k !== "report" && k !== "title") facts[k] = v;
  }
  if ("kb_hit" in sc.expected) facts.kb_hit = sc.expected.kb_hit;
  return facts;
}

function capitalize(s: string): string {
  return s.length ? s[0].toUpperCase() + s.slice(1).toLowerCase() : s;
}

/** The intake message handed to the agent as the first user turn. */
export function renderScenario(sc: Scenario): string {
  const kind = sc.intake.kind ?? "request";
  const lines = [`New ${kind}`];
  for (const [key, value] of Object.entries(sc.intake)) {
    if (key === "kind") continue;
    const label = key === "customer_facing" ? "Customer-facing" : capitalize(key.replace(/_/g, "-"));
    lines.push(`${label}: ${value}`);
  }
  return lines.join("\n");
}

export function getScenario(set: ScenarioSet, id: string): Scenario {
  const sc = set.scenarios.find((s) => s.id === id);
  if (!sc) throw new Error(`unknown scenario ${id}`);
  return sc;
}

export function loadRubric(yamlText: string): Rubric {
  const data = asRecord(YAML.parse(yamlText));
  const criteria: Criterion[] = ((data.criteria as Raw[]) ?? []).map((c) => {
    const kind = String(c.kind) as CriterionKind;
    if (!CRITERION_KINDS.includes(kind)) throw new Error(`unknown criterion kind ${kind} in ${String(c.id)}`);
    const rem = c.remediation ? asRecord(c.remediation) : null;
    const params: Record<string, string | number | boolean> = {};
    for (const [k, v] of Object.entries(asRecord(c.params))) {
      params[k] = typeof v === "number" || typeof v === "boolean" ? v : String(v);
    }
    return {
      id: String(c.id),
      kind,
      description: String(c.description ?? ""),
      weight: c.weight === undefined ? 1 : Number(c.weight),
      forbidden: Boolean(c.forbidden ?? false),
      params,
      remediation: rem
        ? {
            step: String(rem.step),
            rule: String(rem.rule),
            condVars: ((rem.cond_vars as unknown[]) ?? []).map(String),
            onlyWhenExpected: rem.only_when_expected === undefined ? null : Boolean(rem.only_when_expected),
          }
        : null,
    };
  });
  const ids = new Set(criteria.map((c) => c.id));
  if (ids.size !== criteria.length) throw new Error("duplicate criterion ids");
  return {
    procedureSlug: String(data.procedure),
    passThreshold: data.pass_threshold === undefined ? 1 : Number(data.pass_threshold),
    criteria,
  };
}

export function requiredActions(rubric: Rubric): string[] {
  return rubric.criteria.filter((c) => c.kind === "tool_called").map((c) => String(c.params.tool));
}
