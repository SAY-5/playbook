/* Shared data shapes. Mirrors the dataclasses in playbook/ingest, playbook/agent and playbook/evals. */

export interface Citation {
  source: string;
  line: number;
}

export function citeStr(c: Citation): string {
  return `${c.source}:${c.line}`;
}

export interface Rule {
  text: string;
  citation: Citation;
}

export interface Step {
  id: string;
  index: number;
  title: string;
  instruction: string;
  tool: string | null;
  citation: Citation;
  rules: Rule[];
}

export type DecisionKind = "decision" | "forbidden";

export interface DecisionPoint {
  id: string;
  text: string;
  citation: Citation;
  stepId: string | null;
  kind: DecisionKind;
}

export interface Procedure {
  name: string;
  slug: string;
  purpose: string;
  preconditions: Rule[];
  steps: Step[];
  decisionPoints: DecisionPoint[];
  escalationRules: Rule[];
  forbidden: Rule[];
  checks: Rule[];
  sources: string[];
}

export interface Correction {
  stepId: string;
  text: string;
  criterion: string;
  version: number;
  evidence: string;
}

export interface PromptSpec {
  procedureSlug: string;
  version: number;
  parentVersion: number | null;
  corrections: Correction[];
  notes: string;
}

export type JsonValue = string | number | boolean | null | JsonValue[] | { [k: string]: JsonValue };
export type JsonObject = { [k: string]: JsonValue };

export interface ToolCall {
  turn: number;
  toolUseId: string;
  name: string; // dotted name, e.g. jira.create_issue
  args: JsonObject;
  result: JsonObject | null;
  error: string | null;
  durationMs: number;
}

export interface ToolUse {
  id: string;
  name: string; // API name, e.g. jira_create_issue
  input: JsonObject;
}

export interface ModelTurn {
  turn: number;
  stopReason: string | null;
  text: string;
  toolUses: ToolUse[];
  inputTokens: number;
  outputTokens: number;
}

export type RunStatus = "running" | "completed" | "max_steps" | "error";

export interface RunTrace {
  runId: string;
  procedureSlug: string;
  promptVersion: number;
  scenarioId: string;
  mode: "offline";
  model: string;
  systemPrompt: string;
  userMessage: string;
  turns: ModelTurn[];
  toolCalls: ToolCall[];
  finalText: string;
  status: RunStatus;
  error: string | null;
}

export interface Scenario {
  id: string;
  intake: Record<string, string>;
  expected: Record<string, string | boolean>;
  tags: string[];
}

export interface ScenarioSet {
  procedureSlug: string;
  scenarios: Scenario[];
}

export type CriterionKind =
  | "tool_called"
  | "tool_order"
  | "issue_field"
  | "slack_post"
  | "transition"
  | "forbidden_transition"
  | "forbidden_channel"
  | "no_pii_in_slack"
  | "text_absent"
  | "judge";

export interface Remediation {
  step: string;
  rule: string;
  condVars: string[];
  onlyWhenExpected: boolean | null;
}

export interface Criterion {
  id: string;
  kind: CriterionKind;
  description: string;
  weight: number;
  forbidden: boolean;
  params: Record<string, string | number | boolean>;
  remediation: Remediation | null;
}

export interface Rubric {
  procedureSlug: string;
  passThreshold: number;
  criteria: Criterion[];
}

export interface CriterionResult {
  id: string;
  kind: CriterionKind;
  passed: boolean;
  score: number;
  weight: number;
  forbidden: boolean;
  evidence: Record<string, JsonValue>;
  rationale: string;
}

export interface RunGrade {
  runId: string;
  scenarioId: string;
  procedureSlug: string;
  promptVersion: number;
  mode: "offline";
  status: RunStatus;
  results: CriterionResult[];
  score: number;
  passed: boolean;
  forbiddenViolations: number;
  requiredActionsMade: number;
  requiredActionsTotal: number;
}

export interface VersionReport {
  procedureSlug: string;
  promptVersion: number;
  mode: "offline";
  scenarios: number;
  passed: number;
  passRate: number;
  meanScore: number;
  perCriterion: Record<string, number>;
  requiredActionCoverage: number;
  forbiddenViolations: number;
  grades: RunGrade[];
}

export interface Comparison {
  before: number;
  after: number;
  passRateDelta: number;
  criterionDeltas: Record<string, number>;
  newlyPassing: string[];
  newlyFailing: string[];
}

export interface KbArticle {
  id: string;
  title: string;
  keywords: string[];
  resolution: string;
}

export interface JiraIssue {
  id: string;
  key: string;
  fields: {
    project: { key: string };
    summary: string;
    description: string;
    issuetype: { name: string };
    priority: { name: string };
    status: { name: string };
  };
  comments: { id: string; body: string }[];
}

export interface JiraEvent {
  type: "create" | "transition" | "comment";
  key: string;
  status?: string;
  body?: string;
}

export interface SlackMessage {
  channel: string;
  text: string;
  ts: string;
}

export interface SlackChannel {
  id: string;
  name: string;
  topic: { value: string };
}
