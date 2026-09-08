/* Port of playbook/agent/tools.py plus fakes/jira_server.py and fakes/slack_server.py.
   The six tool schemas, the keyword knowledge base, and in-memory Jira and Slack stand-ins with
   inspectable inboxes. */
import type { JiraEvent, JiraIssue, JsonObject, KbArticle, SlackChannel, SlackMessage } from "./types";

export interface ToolSchema {
  name: string;
  description: string;
  inputSchema: { type: "object"; properties: Record<string, unknown>; required: string[] };
}

export const TOOL_SCHEMAS: ToolSchema[] = [
  {
    name: "kb_search",
    description: "Search the internal knowledge base for known issues matching a query.",
    inputSchema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
  },
  {
    name: "jira_create_issue",
    description: "Create a Jira issue. Returns the new issue key.",
    inputSchema: {
      type: "object",
      properties: {
        project: { type: "string" },
        summary: { type: "string" },
        description: { type: "string" },
        issue_type: { type: "string", enum: ["Bug", "Task", "Incident"] },
        priority: { type: "string", enum: ["Highest", "High", "Medium", "Low", "Lowest"] },
      },
      required: ["project", "summary", "priority"],
    },
  },
  {
    name: "jira_transition",
    description: "Move a Jira issue to a new status by name.",
    inputSchema: {
      type: "object",
      properties: { issue_key: { type: "string" }, status: { type: "string" } },
      required: ["issue_key", "status"],
    },
  },
  {
    name: "jira_comment",
    description: "Add a comment to a Jira issue.",
    inputSchema: {
      type: "object",
      properties: { issue_key: { type: "string" }, body: { type: "string" } },
      required: ["issue_key", "body"],
    },
  },
  {
    name: "slack_post",
    description: "Post a message to a Slack channel (for example #support-escalations).",
    inputSchema: {
      type: "object",
      properties: { channel: { type: "string" }, text: { type: "string" } },
      required: ["channel", "text"],
    },
  },
  {
    name: "slack_lookup_channel",
    description: "Find the Slack channel that owns a service or topic.",
    inputSchema: { type: "object", properties: { service: { type: "string" } }, required: ["service"] },
  },
];

export const DOTTED_TO_API: Record<string, string> = {
  "kb.search": "kb_search",
  "jira.create_issue": "jira_create_issue",
  "jira.transition": "jira_transition",
  "jira.comment": "jira_comment",
  "slack.post": "slack_post",
  "slack.lookup_channel": "slack_lookup_channel",
};

export const API_TO_DOTTED: Record<string, string> = Object.fromEntries(
  Object.entries(DOTTED_TO_API).map(([k, v]) => [v, k]),
);

export class KnowledgeBase {
  constructor(public articles: KbArticle[]) {}

  search(query: string): (KbArticle & { score: number })[] {
    const words = new Set(query.toLowerCase().match(/[a-z0-9-]+/g) ?? []);
    const hits: (KbArticle & { score: number })[] = [];
    for (const art of this.articles) {
      const score = art.keywords.filter((k) => words.has(k)).length;
      if (score >= 2) hits.push({ ...art, score });
    }
    hits.sort((a, b) => b.score - a.score);
    return hits;
  }
}

export class FakeJira {
  issues = new Map<string, JiraIssue>();
  events: JiraEvent[] = [];
  private counters = new Map<string, number>();

  reset(): void {
    this.issues.clear();
    this.events = [];
    this.counters.clear();
  }

  create(fields: {
    project: string;
    summary: string;
    description?: string;
    issue_type?: string;
    priority?: string;
  }): { id: string; key: string } {
    if (!fields.project || !fields.summary) {
      throw new Error("ValueError: fields.project.key and fields.summary are required");
    }
    const n = (this.counters.get(fields.project) ?? 100) + 1;
    this.counters.set(fields.project, n);
    const key = `${fields.project}-${n}`;
    const issue: JiraIssue = {
      id: String(10000 + this.issues.size),
      key,
      fields: {
        project: { key: fields.project },
        summary: fields.summary,
        description: fields.description ?? "",
        issuetype: { name: fields.issue_type ?? "Task" },
        priority: { name: fields.priority ?? "Medium" },
        status: { name: "Open" },
      },
      comments: [],
    };
    this.issues.set(key, issue);
    this.events.push({ type: "create", key });
    return { id: issue.id, key };
  }

  transition(key: string, status: string): void {
    const issue = this.issues.get(key);
    if (!issue) throw new Error(`KeyError: ${key}`);
    if (!status) throw new Error("ValueError: transition.name required");
    issue.fields.status = { name: status };
    this.events.push({ type: "transition", key, status });
  }

  comment(key: string, body: string): { id: string } {
    const issue = this.issues.get(key);
    if (!issue) throw new Error(`KeyError: ${key}`);
    if (!body) throw new Error("ValueError: body required");
    const id = String(issue.comments.length + 1);
    issue.comments.push({ id, body });
    this.events.push({ type: "comment", key, body });
    return { id };
  }

  list(): JiraIssue[] {
    return Array.from(this.issues.values());
  }
}

export const DEFAULT_CHANNELS: { name: string; topic: string }[] = [
  { name: "support-escalations", topic: "Escalated support cases" },
  { name: "oncall-sev1", topic: "Pages the sev1 on-call engineer" },
  { name: "incidents", topic: "Incident announcements" },
  { name: "status-updates", topic: "Customer-facing status" },
  { name: "ic-oncall", topic: "Incident commander pages" },
  { name: "team-payments", topic: "Owns payments-api and billing" },
  { name: "team-identity", topic: "Owns auth-service and sso" },
  { name: "team-data", topic: "Owns export-service and analytics" },
  { name: "general", topic: "Company wide" },
];

export class FakeSlack {
  channels: SlackChannel[];
  messages: SlackMessage[] = [];

  constructor(channels = DEFAULT_CHANNELS) {
    this.channels = channels.map((c, i) => ({
      id: `C${String(i + 1).padStart(4, "0")}`,
      name: c.name,
      topic: { value: c.topic },
    }));
  }

  reset(): void {
    this.messages = [];
  }

  postMessage(channelRaw: string, text: string): { ok: true; channel: string; ts: string } | { ok: false; error: string } {
    const channel = String(channelRaw ?? "").replace(/^#+/, "");
    if (!channel || !text) return { ok: false, error: "invalid_arguments" };
    if (!this.channels.some((c) => c.name === channel)) return { ok: false, error: "channel_not_found" };
    const ts = `${1700000000 + this.messages.length}.000100`;
    this.messages.push({ channel: `#${channel}`, text, ts });
    return { ok: true, channel, ts };
  }
}

/** Executes tool calls against the fakes. Every result is a plain JSON object so the trace is complete. */
export class ToolExecutor {
  constructor(
    public kb: KnowledgeBase,
    public jira: FakeJira,
    public slack: FakeSlack,
  ) {}

  execute(name: string, args: JsonObject): JsonObject {
    const str = (k: string): string => (args[k] === undefined || args[k] === null ? "" : String(args[k]));
    switch (name) {
      case "kb_search":
        return { matches: this.kb.search(str("query")) as unknown as JsonObject[] };
      case "jira_create_issue": {
        const data = this.jira.create({
          project: str("project"),
          summary: str("summary"),
          description: str("description"),
          issue_type: args.issue_type === undefined ? "Task" : str("issue_type"),
          priority: str("priority"),
        });
        return { issue_key: data.key, id: data.id };
      }
      case "jira_transition":
        this.jira.transition(str("issue_key"), str("status"));
        return { issue_key: str("issue_key"), status: str("status") };
      case "jira_comment": {
        const data = this.jira.comment(str("issue_key"), str("body"));
        return { issue_key: str("issue_key"), comment_id: data.id };
      }
      case "slack_post": {
        const data = this.slack.postMessage(str("channel"), str("text"));
        if (!data.ok) throw new Error(`RuntimeError: slack error: ${data.error}`);
        return { channel: str("channel"), ts: data.ts };
      }
      case "slack_lookup_channel": {
        const wanted = str("service").toLowerCase();
        for (const ch of this.slack.channels) {
          const topic = ch.topic.value.toLowerCase();
          if (wanted && (ch.name.toLowerCase().includes(wanted) || topic.includes(wanted))) {
            return { channel: `#${ch.name}`, found: true };
          }
        }
        return { channel: null, found: false };
      }
      default:
        throw new Error(`ValueError: unknown tool ${name}`);
    }
  }
}
