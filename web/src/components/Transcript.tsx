/* Transcript viewer: one scenario, one prompt version, stepped through turn by turn. Every entry
   comes straight out of the RunTrace the loop produced, so the arguments and results shown are
   the ones the grader scored. */
import { useEffect, useMemo, useState } from "react";
import { scenarioIds, traceFor, type Arc } from "../sim/arc";
import { condText, parsePrompt, type Directive } from "../sim/engine";
import type { Correction, RunTrace } from "../sim/types";
import { Section } from "./Section";

type EntryKind = "intake" | "model" | "tool" | "final" | "rule" | "ignored";
type Rail = "turns" | "rules";

interface Entry {
  kind: EntryKind;
  label: string;
  meta: string;
  body: string;
}

const pretty = (value: unknown): string => JSON.stringify(value, null, 2);

function buildEntries(trace: RunTrace): Entry[] {
  const entries: Entry[] = [
    { kind: "intake", label: "intake", meta: "first user turn", body: trace.userMessage },
  ];
  for (const turn of trace.turns) {
    const names = turn.toolUses.map((u) => u.name).join(", ");
    entries.push({
      kind: "model",
      label: `model turn ${turn.turn}`,
      meta: `stop_reason=${turn.stopReason ?? "none"} in=${turn.inputTokens} out=${turn.outputTokens}`,
      body: turn.text.trim() || (names ? `requests ${names}` : "(no text)"),
    });
    for (const call of trace.toolCalls.filter((c) => c.turn === turn.turn)) {
      entries.push({
        kind: "tool",
        label: call.name,
        meta: `${call.durationMs} ms${call.error ? " - error" : ""}`,
        body: `arguments\n${pretty(call.args)}\n\nresult\n${call.error ? pretty({ error: call.error }) : pretty(call.result)}`,
      });
    }
  }
  entries.push({
    kind: "final",
    label: "final message",
    meta: `status=${trace.status} run=${trace.runId}`,
    body: trace.finalText,
  });
  return entries;
}

/** What a parsed directive makes the stand-in do, in the grammar's own words. */
function effectOf(d: Directive): string {
  switch (d.kind) {
    case "project":
      return `use project ${d.value}`;
    case "set":
      return `set ${d.field} to "${d.value}"`;
    case "post":
      return `post to ${d.channel}${d.mentionKey ? " mentioning the issue key" : ""}`;
    case "transition":
      return `transition to "${d.value}"${d.elseValue ? `, otherwise "${d.elseValue}"` : ""}`;
    case "exclude":
      return `do not include the customer ${d.value}`;
  }
}

/* The stand-in only obeys prompt lines it can parse, so the rules it extracted and the prose it
   ignored are what explain why one version fails and the next one passes. */
function buildRules(systemPrompt: string, corrections: Correction[]): Entry[] {
  const parsed = parsePrompt(systemPrompt);
  const addedIn = new Map(corrections.map((c) => [c.text.trim(), c.version]));
  const entries: Entry[] = parsed.directives.map((d) => {
    const version = addedIn.get(d.source.trim());
    return {
      kind: "rule",
      label: effectOf(d),
      meta: `${d.stepId ?? "no step"} - ${condText(d.cond)}${version ? ` - added in v${version}` : ""}`,
      body: [
        `prompt line\n${d.source}`,
        `step\n${d.stepId ?? "(outside a step)"}`,
        `condition\n${condText(d.cond)}`,
        `effect\n${effectOf(d)}`,
        version ? `origin\ncorrection added in v${version}` : "origin\nrendered from the SOP",
      ].join("\n\n"),
    };
  });
  for (const line of parsed.ignored) {
    entries.push({
      kind: "ignored",
      label: line.length > 68 ? `${line.slice(0, 68)}...` : line,
      meta: "prose the stand-in ignored",
      body: `ignored prompt line\n${line}\n\nThe stand-in parses rules, not prose, so this line changes nothing it does.`,
    });
  }
  return entries;
}

export interface TranscriptProps {
  arc: Arc;
}

export function Transcript({ arc }: TranscriptProps) {
  const ids = useMemo(() => scenarioIds(arc), [arc]);
  const lastRound = arc.rounds.length - 1;
  const [scenario, setScenario] = useState(ids[0]);
  const [round, setRound] = useState(lastRound);
  const [step, setStep] = useState(0);
  const [rail, setRail] = useState<Rail>("turns");

  useEffect(() => {
    setScenario(ids[0]);
    setRound(arc.rounds.length - 1);
    setStep(0);
  }, [arc, ids]);

  const trace = traceFor(arc, round, scenario);
  const turns = useMemo(() => (trace ? buildEntries(trace) : []), [trace]);
  const rules = useMemo(
    () => (trace ? buildRules(trace.systemPrompt, arc.rounds[round]?.spec.corrections ?? []) : []),
    [trace, arc, round],
  );
  const entries = rail === "turns" ? turns : rules;
  const index = Math.min(step, Math.max(0, entries.length - 1));
  const current = entries[index];
  const grade = arc.rounds[round]?.report.grades.find((g) => g.scenarioId === scenario);

  return (
    <Section
      id="transcript"
      num="01"
      title="One run, turn by turn"
      lede={
        <>
          The loop is bounded and every turn is recorded: the rendered system prompt, each model
          turn with its stop reason, each tool call with its arguments and the JSON the fake Jira,
          Slack or knowledge base returned. Pick a scenario and a prompt version and walk it. The
          second rail tab lists what the stand-in actually parsed out of that version&rsquo;s prompt:
          each rule with its condition and the step it came from, which corrections added it, and
          the prose it ignored.
        </>
      }
      aside={
        <div className="seg" role="group" aria-label="prompt version">
          {arc.rounds.map((r, i) => (
            <button
              key={r.spec.version}
              type="button"
              className="seg__btn"
              aria-pressed={round === i}
              onClick={() => {
                setRound(i);
                setStep(0);
              }}
            >
              v{r.spec.version}
            </button>
          ))}
        </div>
      }
    >
      <div className="transcript">
        <div className="transcript__rail glass">
          <label className="field">
            <span className="field__label">scenario</span>
            <select
              className="field__input"
              value={scenario}
              onChange={(e) => {
                setScenario(e.target.value);
                setStep(0);
              }}
            >
              {ids.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </label>
          <div className="seg seg--rail" role="group" aria-label="rail contents">
            <button
              type="button"
              className="seg__btn"
              aria-pressed={rail === "turns"}
              onClick={() => {
                setRail("turns");
                setStep(0);
              }}
            >
              turns
            </button>
            <button
              type="button"
              className="seg__btn"
              aria-pressed={rail === "rules"}
              onClick={() => {
                setRail("rules");
                setStep(0);
              }}
            >
              what the stand-in parsed
            </button>
          </div>
          <p className="transcript__verdict">
            <span className={`chip ${grade?.passed ? "chip--pass" : "chip--fail"}`}>
              {grade?.passed ? "pass" : "fail"}
            </span>
            <span className="chip">score {grade ? (grade.score * 100).toFixed(0) : "0"}%</span>
            <span className="chip">
              {entries.length} {rail === "turns" ? "entries" : "lines"}
            </span>
          </p>
          <ol className="steps" aria-label={rail === "turns" ? "transcript entries" : "parsed prompt lines"}>
            {entries.map((entry, i) => (
              <li key={`${entry.kind}-${i}`}>
                <button
                  type="button"
                  className={`steps__item steps__item--${entry.kind}`}
                  aria-current={i === index ? "step" : undefined}
                  onClick={() => setStep(i)}
                >
                  <span className="steps__dot" aria-hidden="true" />
                  <span className="steps__label">{entry.label}</span>
                  <span className="steps__meta">{entry.meta}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>

        <div className="transcript__stage glass">
          <div className="transcript__bar">
            <span className="chip chip--accent">
              {index + 1} / {entries.length}
            </span>
            <span className="transcript__title">{current?.label}</span>
            <span className="transcript__meta">{current?.meta}</span>
            <span className="transcript__nav">
              <button type="button" className="btn btn--tight" onClick={() => setStep(Math.max(0, index - 1))} disabled={index === 0}>
                Previous
              </button>
              <button
                type="button"
                className="btn btn--tight btn--primary"
                onClick={() => setStep(Math.min(entries.length - 1, index + 1))}
                disabled={index >= entries.length - 1}
              >
                Next
              </button>
            </span>
          </div>
          <div className="transcript__bodywrap">
            <pre className="mono-block transcript__body" key={`${rail}-${scenario}-${round}-${index}`}>
              {current?.body}
            </pre>
          </div>
        </div>
      </div>
    </Section>
  );
}
