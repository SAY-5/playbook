/* Transcript viewer: one scenario, one prompt version, stepped through turn by turn. Every entry
   comes straight out of the RunTrace the loop produced, so the arguments and results shown are
   the ones the grader scored. */
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { scenarioIds, traceFor, type Arc } from "../sim/arc";
import type { RunTrace } from "../sim/types";
import { Section } from "./Section";

type EntryKind = "intake" | "model" | "tool" | "final";

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

export interface TranscriptProps {
  arc: Arc;
}

export function Transcript({ arc }: TranscriptProps) {
  const reduced = useReducedMotion();
  const ids = useMemo(() => scenarioIds(arc), [arc]);
  const lastRound = arc.rounds.length - 1;
  const [scenario, setScenario] = useState(ids[0]);
  const [round, setRound] = useState(lastRound);
  const [step, setStep] = useState(0);

  useEffect(() => {
    setScenario(ids[0]);
    setRound(arc.rounds.length - 1);
    setStep(0);
  }, [arc, ids]);

  const trace = traceFor(arc, round, scenario);
  const entries = useMemo(() => (trace ? buildEntries(trace) : []), [trace]);
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
          Slack or knowledge base returned. Pick a scenario and a prompt version and walk it.
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
          <p className="transcript__verdict">
            <span className={`chip ${grade?.passed ? "chip--pass" : "chip--fail"}`}>
              {grade?.passed ? "pass" : "fail"}
            </span>
            <span className="chip">score {grade ? (grade.score * 100).toFixed(0) : "0"}%</span>
            <span className="chip">{entries.length} entries</span>
          </p>
          <ol className="steps" aria-label="transcript entries">
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
            <AnimatePresence mode="wait" initial={false}>
              <motion.pre
                key={`${scenario}-${round}-${index}`}
                className="mono-block transcript__body"
                initial={reduced ? false : { opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduced ? undefined : { opacity: 0, y: -8 }}
                transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              >
                {current?.body}
              </motion.pre>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </Section>
  );
}
