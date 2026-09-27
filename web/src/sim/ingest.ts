/* Port of playbook/ingest/parser.py: SOP markdown plus walkthrough transcript into a Procedure with citations. */
import type { Citation, DecisionPoint, Procedure, Rule, Step } from "./types";

const STEP_RE = /^(\d+)\.\s+(.*?)(?:\s+\{#([\w-]+)\})?(?:\s+\(tool:\s*([\w.]+)\))?\s*$/;
const TRANSCRIPT_RE = /^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s+([^:]+):\s+(.+)$/;
const SENTENCE_RE = /(?<=[.!?])\s+(?=[A-Z])/;
const STOPWORDS = new Set([
  "the", "a", "an", "to", "of", "in", "and", "or", "is", "it", "for", "on", "with", "that", "this", "as",
  "be", "if", "when", "then", "we", "i", "you", "so", "at", "by", "from", "do", "not", "never", "always",
  "also", "one", "them", "they", "its", "their", "our", "get", "gets",
]);
const DECISION_HINTS = ["if ", "when ", "unless ", "otherwise", "exception", "must", "always"];
const FORBIDDEN_HINTS = ["never ", "do not ", "don't ", "must not "];
// A priority matrix stated in prose: "sev1 is Highest, sev2 is High" or "full outage is Highest".
const MATRIX_RE = /\b[\w-]+ is (?:highest|high|medium|low|lowest)\b/;
const CHANNEL_RE = /#[\w-]+/g;
const POSTING_RE = /\b(?:post|posts|page|pages|announce|slack)\b/;

function isDecision(low: string): boolean {
  return DECISION_HINTS.some((h) => low.includes(h)) || MATRIX_RE.test(low);
}

export function slugify(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function tokens(text: string): Set<string> {
  const out = new Set<string>();
  for (const t of text.toLowerCase().match(/[a-z0-9#.-]+/g) ?? []) {
    if (!STOPWORDS.has(t) && t.length > 2) out.add(t);
  }
  return out;
}

export function parseSop(text: string, source = "sop.md"): Procedure {
  const lines = text.split(/\r?\n/);
  let name = "";
  let purpose = "";
  let section = "";
  const proc: Procedure = {
    name: "",
    slug: "",
    purpose: "",
    preconditions: [],
    steps: [],
    decisionPoints: [],
    escalationRules: [],
    forbidden: [],
    checks: [],
    sources: [source],
  };
  let current: Step | null = null;

  lines.forEach((raw, i) => {
    const lineno = i + 1;
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) return;
    if (line.startsWith("# ") && !name) {
      name = line.slice(2).trim();
      return;
    }
    if (line.toLowerCase().startsWith("purpose:")) {
      purpose = line.slice(line.indexOf(":") + 1).trim();
      return;
    }
    if (line.startsWith("## ")) {
      section = line.slice(3).trim().toLowerCase();
      current = null;
      return;
    }
    const cite: Citation = { source, line: lineno };
    if (section === "steps") {
      const m = STEP_RE.exec(line);
      if (m) {
        const title = m[2].trim();
        current = {
          id: m[3] || slugify(title),
          index: parseInt(m[1], 10),
          title,
          instruction: "",
          tool: m[4] || null,
          citation: cite,
          rules: [],
        };
        proc.steps.push(current);
      } else if (current) {
        const body = line.trim();
        if (body.startsWith("- ")) current.rules.push({ text: body.slice(2).trim(), citation: cite });
        else current.instruction = `${current.instruction} ${body}`.trim();
      }
      return;
    }
    if (line.trim().startsWith("- ")) {
      const rule: Rule = { text: line.trim().slice(2).trim(), citation: cite };
      if (section === "preconditions") proc.preconditions.push(rule);
      else if (section === "escalation") proc.escalationRules.push(rule);
      else if (section === "never") proc.forbidden.push(rule);
      else if (section === "checks") proc.checks.push(rule);
    }
  });

  if (!name) throw new Error(`${source}: missing '# <name>' heading`);
  if (!proc.steps.length) throw new Error(`${source}: no numbered steps found under '## Steps'`);
  proc.name = name;
  proc.slug = slugify(name);
  proc.purpose = purpose;
  return proc;
}

function stepText(step: Step): string {
  return `${step.title} ${step.instruction} ${step.tool ?? ""} ` + step.rules.map((r) => r.text).join(" ");
}

/* The step a decision belongs to: the step whose own text names a channel the sentence names; for
   a priority matrix, the step that sets the priority; for a sentence about posting or paging, the
   first step whose tool is slack.post; otherwise the step with the largest keyword overlap. */
function bestStep(proc: Procedure, sentence: string): string | null {
  const low = sentence.toLowerCase();
  const channels = new Set(low.match(CHANNEL_RE) ?? []);
  if (channels.size) {
    for (const step of proc.steps) {
      const named = stepText(step).toLowerCase().match(CHANNEL_RE) ?? [];
      if (named.some((c) => channels.has(c))) return step.id;
    }
  }
  if (MATRIX_RE.test(low)) {
    for (const step of proc.steps) if (stepText(step).toLowerCase().includes("priority")) return step.id;
  }
  if (channels.size || POSTING_RE.test(low)) {
    for (const step of proc.steps) if (step.tool === "slack.post") return step.id;
  }
  const words = tokens(sentence);
  let best: string | null = null;
  let bestScore = 0;
  for (const step of proc.steps) {
    const hayTokens = tokens(stepText(step));
    let score = 0;
    for (const w of words) if (hayTokens.has(w)) score++;
    if (score > bestScore) {
      best = step.id;
      bestScore = score;
    }
  }
  return best;
}

export function parseWalkthrough(text: string, proc: Procedure, source = "walkthrough.md"): DecisionPoint[] {
  const found: DecisionPoint[] = [];
  text.split(/\r?\n/).forEach((raw, i) => {
    const m = TRANSCRIPT_RE.exec(raw.trim());
    if (!m || m[2].trim().toLowerCase() !== "expert") return;
    for (const sentence of m[3].trim().split(SENTENCE_RE)) {
      const low = sentence.toLowerCase();
      let kind: DecisionPoint["kind"];
      if (FORBIDDEN_HINTS.some((h) => low.includes(h))) kind = "forbidden";
      else if (isDecision(low)) kind = "decision";
      else continue;
      found.push({
        id: `${kind[0]}${found.length + 1}`,
        text: sentence.trim(),
        citation: { source, line: i + 1 },
        stepId: bestStep(proc, sentence),
        kind,
      });
    }
  });
  return found;
}

export function ingestProcedure(sop: string, walkthrough: string | null): Procedure {
  const proc = parseSop(sop);
  if (walkthrough !== null) {
    proc.decisionPoints = parseWalkthrough(walkthrough, proc);
    proc.sources.push("walkthrough.md");
  }
  return proc;
}
