/* Port of playbook/agent/prompt.py: versioned PromptSpec rendered from a Procedure plus corrections. */
import { citeStr, type Correction, type Procedure, type PromptSpec } from "./types";

export function initialSpec(procedureSlug: string): PromptSpec {
  return {
    procedureSlug,
    version: 1,
    parentVersion: null,
    corrections: [],
    notes: "initial prompt built from the ingested procedure",
  };
}

export function specLabel(spec: PromptSpec): string {
  return `v${spec.version}`;
}

/** Create the next version. Existing corrections are kept; duplicates are dropped. */
export function withCorrections(spec: PromptSpec, fresh: Correction[], notes: string): PromptSpec {
  const seen = new Set(spec.corrections.map((c) => `${c.stepId} ${c.text}`));
  const merged = [...spec.corrections];
  for (const c of fresh) {
    const key = `${c.stepId} ${c.text}`;
    if (!seen.has(key)) {
      merged.push({ ...c, version: spec.version + 1 });
      seen.add(key);
    }
  }
  return {
    procedureSlug: spec.procedureSlug,
    version: spec.version + 1,
    parentVersion: spec.version,
    corrections: merged,
    notes,
  };
}

export function renderPrompt(spec: PromptSpec, proc: Procedure): string {
  const byStep = new Map<string, Correction[]>();
  for (const c of spec.corrections) {
    const list = byStep.get(c.stepId) ?? [];
    list.push(c);
    byStep.set(c.stepId, list);
  }
  const out: string[] = [
    `You are an operations agent executing the procedure "${proc.name}" (prompt ${specLabel(spec)}).`,
    proc.purpose,
    "Work through the steps in order, calling one tool at a time and using only the tools " +
      "provided. Read each tool result before the next call. When every step is done, reply " +
      "with a one-line summary and stop.",
    "",
  ];
  if (proc.preconditions.length) {
    out.push("## Preconditions");
    for (const r of proc.preconditions) out.push(`- ${r.text}`);
    out.push("");
  }
  out.push("## Steps");
  for (const step of proc.steps) {
    const tool = step.tool ? ` (tool: ${step.tool})` : "";
    out.push(`### Step ${step.index}: ${step.title} [${step.id}]${tool}`);
    if (step.instruction) out.push(step.instruction);
    for (const r of step.rules) out.push(`- ${r.text}`);
    const fixes = byStep.get(step.id) ?? [];
    if (fixes.length) {
      out.push("Corrections:");
      for (const c of fixes) out.push(`- (v${c.version}) ${c.text}`);
    }
    out.push("");
  }
  const decisions = proc.decisionPoints.filter((d) => d.kind === "decision");
  if (decisions.length) {
    out.push("## Decision points (from the walkthrough)");
    for (const d of decisions) {
      const tag = d.stepId ? `[${d.stepId}] ` : "";
      out.push(`- ${tag}${d.text} (${citeStr(d.citation)})`);
    }
    out.push("");
  }
  if (proc.escalationRules.length) {
    out.push("## Escalation");
    for (const r of proc.escalationRules) out.push(`- ${r.text}`);
    out.push("");
  }
  const forbidden = [
    ...proc.forbidden.map((r) => r.text),
    ...proc.decisionPoints.filter((d) => d.kind === "forbidden").map((d) => d.text),
  ];
  if (forbidden.length) {
    out.push("## Never");
    for (const t of Array.from(new Set(forbidden))) out.push(`- ${t}`);
    out.push("");
  }
  if (proc.checks.length) {
    out.push("## Checks before finishing");
    for (const r of proc.checks) out.push(`- ${r.text}`);
    out.push("");
  }
  return out.join("\n").replace(/\s+$/, "") + "\n";
}
