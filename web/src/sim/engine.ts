/* Port of fakes/model_server.py: the deterministic stand-in for the Messages API used in offline mode.

   It walks the `### Step` headers of the system prompt in order and calls each step's tool, but the
   arguments and the conditional calls are decided only by directives it can parse, for example
   `When severity is sev1, post to #oncall-sev1 mentioning the issue key.` Prose it cannot parse is
   ignored, which is what makes the feedback loop observable. */
import type { Prng } from "./prng";
import type { JsonObject, JsonValue } from "./types";

const STEP_HEADER = /^### Step (\d+): (.*?) \[([\w-]+)\](?: \(tool: ([\w.]+)\))?/;
const COND_ACTION = /^(?:if|when)\s+(.+?),\s*(.+)$/i;
const OTHERWISE = /^otherwise\s+(.+)$/i;
const SEV = /\bsev[1-4]\b/i;
export const EMAIL_RE = /[\w.+-]+@[\w-]+\.[\w.]+/;
export const PHONE_RE = /\+?\d[\d\s().-]{7,}\d/;
const IMPACTS = ["full outage", "partial outage", "degraded", "internal"];
const TIERS = ["enterprise", "pro", "free"];

export type Facts = Record<string, JsonValue | undefined>;

export interface Cond {
  severity: string | null;
  severityUnknown: boolean;
  tier: string | null;
  kbHit: boolean | null;
  customerFacing: boolean | null;
  impact: string | null;
  reportPhrase: string | null;
  slackContext: boolean;
}

function emptyCond(): Cond {
  return {
    severity: null,
    severityUnknown: false,
    tier: null,
    kbHit: null,
    customerFacing: null,
    impact: null,
    reportPhrase: null,
    slackContext: false,
  };
}

export function specificity(c: Cond): number {
  let n = 0;
  for (const v of [c.severity, c.tier, c.kbHit, c.customerFacing, c.impact, c.reportPhrase]) {
    if (v !== null) n++;
  }
  return n + (c.severityUnknown ? 1 : 0);
}

export function condHolds(c: Cond, facts: Facts): boolean {
  if (c.severity && facts.severity !== c.severity) return false;
  if (c.severityUnknown && facts.severity_stated) return false;
  if (c.tier && facts.tier !== c.tier) return false;
  if (c.kbHit !== null && Boolean(facts.kb_hit) !== c.kbHit) return false;
  if (c.customerFacing !== null && Boolean(facts.customer_facing) !== c.customerFacing) return false;
  if (c.impact && facts.impact !== c.impact) return false;
  if (c.reportPhrase && !String(facts.report ?? "").toLowerCase().includes(c.reportPhrase)) return false;
  return true;
}

/** Describe a condition in the grammar's own words (for the UI). */
export function condText(c: Cond | null): string {
  if (!c) return "always";
  const parts: string[] = [];
  if (c.severity) parts.push(`severity is ${c.severity}`);
  if (c.severityUnknown) parts.push("severity is not stated");
  if (c.tier) parts.push(`tier is ${c.tier}`);
  if (c.kbHit !== null) parts.push(c.kbHit ? "a KB match is found" : "no KB match is found");
  if (c.customerFacing !== null) parts.push(c.customerFacing ? "customer-facing" : "not customer-facing");
  if (c.impact) parts.push(`impact is ${c.impact}`);
  if (c.reportPhrase) parts.push(`report mentions "${c.reportPhrase}"`);
  if (c.slackContext) parts.push("posting to Slack");
  return parts.length ? parts.join(" and ") : "always";
}

function rstripDots(s: string): string {
  return s.replace(/\.+$/, "");
}

/** Return a Cond when every clause is understood, otherwise null. */
export function parseCond(text: string): Cond | null {
  const cond = emptyCond();
  for (let clause of text.trim().toLowerCase().split(/\s+and\s+/)) {
    clause = rstripDots(clause.trim());
    const m = SEV.exec(clause);
    if (m && !clause.includes("not stated") && !clause.includes("unknown")) {
      cond.severity = m[0].toLowerCase();
      continue;
    }
    if (clause.includes("severity") && (clause.includes("not stated") || clause.includes("unknown"))) {
      cond.severityUnknown = true;
      continue;
    }
    const tier = TIERS.find((t) => clause.includes(t));
    if (tier && (clause.includes("tier") || clause.includes("account"))) {
      cond.tier = tier;
      continue;
    }
    if (clause.includes("kb") || clause.includes("knowledge base")) {
      cond.kbHit = !(clause.includes("no ") || clause.includes("nothing") || clause.includes("not "));
      continue;
    }
    if (clause.includes("customer-facing") || clause.includes("customer facing")) {
      cond.customerFacing = !clause.startsWith("not ") && !clause.includes(" not ");
      continue;
    }
    const impact = IMPACTS.find((i) => clause.includes(i));
    if (impact && clause.includes("impact")) {
      cond.impact = impact;
      continue;
    }
    const pm = /report mentions "([^"]+)"/.exec(clause);
    if (pm) {
      cond.reportPhrase = pm[1].toLowerCase();
      continue;
    }
    if (clause.includes("posting to slack")) {
      cond.slackContext = true;
      continue;
    }
    return null;
  }
  return cond;
}

export type DirectiveKind = "project" | "set" | "post" | "transition" | "exclude";

export interface Directive {
  kind: DirectiveKind;
  cond: Cond | null;
  stepId: string | null;
  field: string;
  value: string;
  channel: string;
  mentionKey: boolean;
  elseValue: string;
  /** The prompt line the directive came from (for the UI). */
  source: string;
}

function directive(kind: DirectiveKind, cond: Cond | null, stepId: string | null, extra: Partial<Directive>, source: string): Directive {
  return { kind, cond, stepId, field: "", value: "", channel: "", mentionKey: false, elseValue: "", source, ...extra };
}

export function parseAction(text: string, cond: Cond | null, stepId: string | null, source: string): Directive | null {
  const t = rstripDots(text.trim());
  const low = t.toLowerCase();
  let m: RegExpExecArray | null;
  if ((m = /^use project (\w+)/i.exec(t))) return directive("project", cond, stepId, { value: m[1].toUpperCase() }, source);
  if ((m = /^set (\w+) to "([^"]+)"/i.exec(t))) return directive("set", cond, stepId, { field: m[1].toLowerCase(), value: m[2] }, source);
  if ((m = /^treat severity as (sev[1-4])/i.exec(t))) return directive("set", cond, stepId, { field: "severity", value: m[1].toLowerCase() }, source);
  if ((m = /^post to (#[\w-]+|the service channel)( mentioning the issue key)?/i.exec(t))) {
    return directive("post", cond, stepId, { channel: m[1].toLowerCase(), mentionKey: Boolean(m[2]) }, source);
  }
  if ((m = /^transition to "([^"]+)"/i.exec(t))) return directive("transition", cond, stepId, { value: m[1] }, source);
  if ((m = /^do not include the customer (email|phone number)/.exec(low))) return directive("exclude", cond, stepId, { value: m[1] }, source);
  return null;
}

export interface ParsedPrompt {
  steps: [string, string | null][];
  directives: Directive[];
  /** Prompt lines that carried no parseable directive (for the UI). */
  ignored: string[];
}

export function parsePrompt(system: string): ParsedPrompt {
  const parsed: ParsedPrompt = { steps: [], directives: [], ignored: [] };
  let stepId: string | null = null;
  for (const raw of system.split(/\r?\n/)) {
    let line = raw.trim();
    if (!line) continue;
    const hm = STEP_HEADER.exec(line);
    if (hm) {
      stepId = hm[3];
      parsed.steps.push([stepId, hm[4] ?? null]);
      continue;
    }
    if (line.startsWith("## ")) {
      stepId = null;
      continue;
    }
    if (line.startsWith("- ")) line = line.slice(2);
    line = line.replace(/^\(v\d+\)\s*/, "");
    let any = false;
    for (let sentence of line.split(/(?<=[.!])\s+(?=[A-Z])/)) {
      sentence = sentence.trim();
      const cm = COND_ACTION.exec(sentence);
      const om = OTHERWISE.exec(sentence);
      let d: Directive | null;
      if (cm) {
        const cond = parseCond(cm[1]);
        if (cond === null) continue;
        d = parseAction(cm[2], cond, stepId, sentence);
      } else if (om) {
        d = parseAction(om[1], null, stepId, sentence);
        if (d && d.kind === "transition") {
          for (let i = parsed.directives.length - 1; i >= 0; i--) {
            const prev = parsed.directives[i];
            if (prev.kind === "transition" && prev.cond !== null) {
              prev.elseValue = d.value;
              break;
            }
          }
          d = null;
          any = true;
        }
      } else {
        d = parseAction(sentence, null, stepId, sentence);
      }
      if (d !== null) {
        parsed.directives.push(d);
        any = true;
      }
    }
    if (!any && stepId !== null && line !== "Corrections:") parsed.ignored.push(line);
  }
  return parsed;
}

export function parseIntake(text: string): Facts {
  const facts: Facts = {};
  for (const line of text.split(/\r?\n/)) {
    const m = /^([A-Za-z][\w -]*):\s*(.*)$/.exec(line.trim());
    if (m) facts[m[1].trim().toLowerCase().replace(/ /g, "_")] = m[2].trim();
  }
  const sev = String(facts.severity ?? "").toLowerCase();
  facts.severity_stated = /^sev[1-4]$/i.test(sev);
  facts.severity = facts.severity_stated ? sev : null;
  facts.tier = String(facts.tier ?? "").toLowerCase() || null;
  facts.impact = String(facts.impact ?? "").toLowerCase() || null;
  const cf = String(facts["customer-facing"] ?? facts.customer_facing ?? "").toLowerCase();
  facts.customer_facing = cf === "yes" || cf === "true";
  return facts;
}

function formatMap(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? values[key] : whole));
}

export interface PlannedCall {
  name: string;
  input: JsonObject;
}

export interface EngineState {
  posted: string[];
  issue_key?: string;
  kb_matches?: JsonObject[];
  kb_hit?: boolean;
  service_channel?: string;
}

export interface MessageBlock {
  type: "text" | "tool_use" | "tool_result";
  text?: string;
  id?: string;
  name?: string;
  input?: JsonObject;
  tool_use_id?: string;
  content?: string;
  is_error?: boolean;
}

export interface Message {
  role: "user" | "assistant";
  content: string | MessageBlock[];
}

export interface MessagesRequest {
  model: string;
  system: string;
  messages: Message[];
}

export interface MessagesResponse {
  id: string;
  type: "message";
  role: "assistant";
  model: string;
  content: MessageBlock[];
  stop_reason: "tool_use" | "end_turn";
  usage: { input_tokens: number; output_tokens: number };
}

export class RuleEngine {
  constructor(
    private prng: Prng,
    public model = "fake-model",
  ) {}

  pick(directives: Directive[], fieldName: string, facts: Facts): string | null {
    let best: Directive | null = null;
    for (const d of directives) {
      if (d.kind !== "set" || d.field !== fieldName) continue;
      if (d.cond !== null && !condHolds(d.cond, facts)) continue;
      const spec = d.cond ? specificity(d.cond) : 0;
      const bestSpec = best && best.cond ? specificity(best.cond) : 0;
      if (best === null || spec >= bestSpec) best = d;
    }
    return best ? best.value : null;
  }

  facts(parsed: ParsedPrompt, intake: string, state: EngineState): Facts {
    const facts = parseIntake(intake);
    Object.assign(facts, state as unknown as Facts);
    if (facts.severity === null || facts.severity === undefined) {
      facts.severity = this.pick(parsed.directives, "severity", facts) ?? "sev3";
    }
    return facts;
  }

  plan(parsed: ParsedPrompt, intake: string, state: EngineState): PlannedCall[] {
    const facts = this.facts(parsed, intake, state);
    const ds = parsed.directives;
    const project = ds.find((d) => d.kind === "project")?.value ?? "OPS";
    const excluded = new Set(
      ds.filter((d) => d.kind === "exclude" && (d.cond === null || condHolds(d.cond, facts))).map((d) => d.value),
    );
    const title = String(facts.title ?? "untitled");
    const key = state.issue_key ?? "";
    const contact = String(facts.contact ?? "");
    const isIncident = "service" in facts;
    const fmt: Record<string, string> = {
      severity: String(facts.severity ?? ""),
      title,
      impact: String(facts.impact ?? ""),
      service: String(facts.service ?? ""),
      account: String(facts.account ?? ""),
    };

    const postText = (mention: boolean): string => {
      const parts: string[] = [];
      if (mention && key) parts.push(`${key}:`);
      parts.push(`[${facts.impact || facts.severity}] ${title}`);
      if (facts.account) parts.push(`(account ${facts.account})`);
      if (isIncident) parts.push("Status: investigating.");
      if (contact) {
        const kind = EMAIL_RE.test(contact) ? "email" : PHONE_RE.test(contact) ? "phone number" : null;
        if (kind && !excluded.has(kind)) parts.push(`Contact: ${contact}`);
      }
      return parts.join(" ");
    };

    const firstPostStep = parsed.steps.find(([, tool]) => tool === "slack.post")?.[0] ?? null;
    const transitionStep = parsed.steps.find(([, tool]) => tool === "jira.transition")?.[0] ?? null;
    const calls: PlannedCall[] = [];
    for (const [sid, tool] of parsed.steps) {
      if (tool === "kb.search") {
        calls.push({ name: "kb_search", input: { query: title } });
      } else if (tool === "slack.lookup_channel") {
        calls.push({ name: "slack_lookup_channel", input: { service: String(facts.service ?? "") } });
      } else if (tool === "jira.create_issue") {
        const summaryT = this.pick(ds, "summary", facts) ?? "{title}";
        calls.push({
          name: "jira_create_issue",
          input: {
            project,
            summary: formatMap(summaryT, fmt),
            description: `Account ${facts.account ?? "n/a"}. ${facts.report ?? ""}`.trim(),
            issue_type: isIncident ? "Incident" : "Bug",
            priority: this.pick(ds, "priority", facts) ?? "Medium",
          },
        });
      } else if (tool === "jira.comment") {
        const matches = state.kb_matches ?? [];
        const kb = matches.map((m) => `${String(m.id)} ${String(m.title)}`).join("; ") || "no KB matches";
        const channels = state.posted ?? [];
        let body = `KB: ${kb}. Account ${facts.account ?? "n/a"} (${facts.tier || "n/a"}).`;
        if (isIncident) body = `Notified: ${channels.join(", ") || "none"}. Impact: ${facts.impact}.`;
        calls.push({ name: "jira_comment", input: { issue_key: key, body } });
      } else if (tool === "slack.post") {
        const posts = new Map<string, boolean>();
        for (const d of ds) {
          if (d.kind !== "post") continue;
          const owner = d.stepId ?? firstPostStep;
          if (owner !== sid || (d.cond !== null && !condHolds(d.cond, facts))) continue;
          const ch = d.channel === "the service channel" ? state.service_channel ?? "" : d.channel;
          if (!ch) continue;
          posts.set(ch, (posts.get(ch) ?? false) || d.mentionKey);
        }
        for (const [ch, mention] of posts) {
          calls.push({ name: "slack_post", input: { channel: ch, text: postText(mention) } });
        }
      } else if (tool === "jira.transition") {
        let status: string | null = null;
        for (const d of ds) {
          if (d.kind !== "transition" || (d.stepId ?? transitionStep) !== sid) continue;
          if (d.cond === null || condHolds(d.cond, facts)) {
            status = d.value;
            break;
          }
          if (d.elseValue) status = d.elseValue;
        }
        if (status) calls.push({ name: "jira_transition", input: { issue_key: key, status } });
      }
    }
    return calls;
  }

  static stateFrom(messages: Message[]): [number, EngineState] {
    const names = new Map<string, string>();
    const inputs = new Map<string, JsonObject>();
    const state: EngineState = { posted: [] };
    let done = 0;
    for (const msg of messages) {
      if (!Array.isArray(msg.content)) continue;
      for (const block of msg.content) {
        if (block.type === "tool_use" && block.id) {
          names.set(block.id, block.name ?? "");
          inputs.set(block.id, block.input ?? {});
          done++;
        } else if (block.type === "tool_result" && block.tool_use_id) {
          const name = names.get(block.tool_use_id);
          let data: JsonObject = {};
          try {
            data = block.content ? (JSON.parse(block.content) as JsonObject) : {};
          } catch {
            data = {};
          }
          if (name === "jira_create_issue" && data.issue_key) {
            state.issue_key = String(data.issue_key);
          } else if (name === "kb_search") {
            const matches = Array.isArray(data.matches) ? (data.matches as JsonObject[]) : [];
            state.kb_matches = matches;
            state.kb_hit = matches.length > 0;
          } else if (name === "slack_lookup_channel") {
            state.service_channel = data.channel ? String(data.channel) : "";
          } else if (name === "slack_post") {
            state.posted.push(String(inputs.get(block.tool_use_id)?.channel ?? ""));
          }
        }
      }
    }
    return [done, state];
  }

  respond(request: MessagesRequest): MessagesResponse {
    const system = request.system ?? "";
    const messages = request.messages ?? [];
    if (!messages.length) throw new Error("messages required");
    const first = messages[0].content;
    const intake = typeof first === "string" ? first : first.map((b) => b.text ?? "").join("");
    const parsed = parsePrompt(system);
    const [done, state] = RuleEngine.stateFrom(messages);
    const calls = this.plan(parsed, intake, state);
    const model = request.model || this.model;
    const inTokens = Math.floor((system.length + messages.reduce((n, m) => n + JSON.stringify(m).length, 0)) / 4);

    let content: MessageBlock[];
    let stop: "tool_use" | "end_turn";
    if (done < calls.length) {
      const call = calls[done];
      content = [
        { type: "text", text: `Step ${done + 1}: calling ${call.name}.` },
        { type: "tool_use", id: `toolu_${this.prng.hex(16)}`, name: call.name, input: call.input },
      ];
      stop = "tool_use";
    } else {
      const key = state.issue_key || "no ticket";
      content = [{ type: "text", text: `Procedure complete. Ticket ${key}; ${done} tool calls.` }];
      stop = "end_turn";
    }
    return {
      id: `msg_${this.prng.hex(20)}`,
      type: "message",
      role: "assistant",
      model,
      content,
      stop_reason: stop,
      usage: { input_tokens: inTokens, output_tokens: Math.floor(JSON.stringify(content).length / 4) },
    };
  }
}
