/* Full run: replay the log the loop produced for this procedure, then print the summary block and
   the self-check result. The arc itself is computed once when the page loads; pressing run
   streams the recorded log so the sequence is readable. */
import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../hooks/motion";
import { FIXTURES } from "../fixtures";
import type { Arc } from "../sim/arc";
import { pct } from "../sim/report";
import { selfCheck, type SelfCheckResult } from "../sim/selfcheck";
import { Section } from "./Section";

type Status = "idle" | "running" | "done";

/** What the replay is about to print, so the console is never a blank box. */
function idlePreamble(arc: Arc): string {
  return [
    `$ playbook loop procedures/${arc.dir} --max-rounds 5`,
    "",
    `  ${arc.scenarios} scenarios, ${arc.rounds.length} prompt versions, ${arc.log.length} log lines`,
    "  each line is one graded run: version, scenario, verdict, score, tool calls",
    "",
    "  press Run to replay it",
  ].join("\n");
}

export interface FullRunProps {
  arc: Arc;
}

export function FullRun({ arc }: FullRunProps) {
  const reduced = useReducedMotion();
  const [status, setStatus] = useState<Status>("idle");
  const [shown, setShown] = useState(0);
  const [check, setCheck] = useState<SelfCheckResult | null>(null);
  const logRef = useRef<HTMLPreElement>(null);
  const lines = arc.log;

  useEffect(() => {
    setStatus("idle");
    setShown(0);
    setCheck(null);
  }, [arc]);

  useEffect(() => {
    if (status !== "running") return undefined;
    if (shown >= lines.length) {
      setStatus("done");
      setCheck(selfCheck(FIXTURES));
      return undefined;
    }
    const id = window.setTimeout(() => setShown((n) => n + 1), 26);
    return () => window.clearTimeout(id);
  }, [status, shown, lines.length]);

  useEffect(() => {
    if (status === "running" && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [shown, status]);

  const start = () => {
    setCheck(null);
    setShown(reduced ? lines.length : 0);
    setStatus("running");
  };

  const progress = lines.length ? Math.round((Math.min(shown, lines.length) / lines.length) * 100) : 0;
  const visible = lines.slice(0, shown).join("\n");

  return (
    <Section
      id="run"
      num="04"
      title="Run the whole arc"
      lede={
        <>
          This replays the run the page performed on load: prompt v1 across every scenario, the
          grade, the corrections, the next version, and so on until the pass rate stops moving. The
          summary block underneath is the one the self-check asserts against the measured results in
          the repository README.
        </>
      }
      aside={
        <span className="seg" role="group" aria-label="run controls">
          <button type="button" className="seg__btn seg__btn--go" onClick={start} disabled={status === "running"}>
            {status === "idle" ? "Run" : status === "running" ? "Running" : "Run again"}
          </button>
          <button type="button" className="seg__btn" onClick={() => setShown(lines.length)} disabled={status !== "running"}>
            Skip
          </button>
        </span>
      }
    >
      <div className="run">
        <div className="run__console glass">
          <div className="run__bar">
            <span className="chip chip--accent">{arc.slug}</span>
            <span className="chip">{arc.scenarios} scenarios</span>
            <span className="chip">{arc.rounds.length} versions</span>
            <span className="run__progress" aria-hidden="true">
              <span className="run__progressfill" style={{ width: `${progress}%` }} />
            </span>
            <span className="run__pct">{progress}%</span>
          </div>
          <pre className="mono-block run__log" ref={logRef} aria-label="run log" tabIndex={0}>
            {status === "idle" ? idlePreamble(arc) : visible}
          </pre>
        </div>

        <div className="run__side">
          <div className="glass run__versions">
            <h3 className="panel__title">Versions</h3>
            <ul className="versions">
              {arc.rounds.map((r) => (
                <li key={r.spec.version}>
                  <span className="versions__tag">v{r.spec.version}</span>
                  <span className="versions__bar" aria-hidden="true">
                    <span className="versions__fill" style={{ width: `${r.report.passRate * 100}%` }} />
                  </span>
                  <span className="versions__rate">{pct(r.report.passRate)}</span>
                  <span className="versions__note">
                    {r.corrections.length ? `+${r.corrections.length} corrections` : "from the SOP alone"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div className="glass run__summary">
            <h3 className="panel__title">Summary</h3>
            <pre className="mono-block">{status === "done" ? arc.summary : "(prints when the replay finishes)"}</pre>
          </div>
          <div className="glass run__check" role="status" aria-live="polite">
            <h3 className="panel__title">Self-check</h3>
            {check ? (
              <>
                <p className={`run__verdict ${check.ok ? "is-pass" : "is-fail"}`}>
                  {check.passed}/{check.total} assertions passed
                </p>
                <ul className="run__checks">
                  {check.assertions.slice(0, 7).map((a) => (
                    <li key={a.name} className={a.ok ? "is-pass" : "is-fail"}>
                      <span aria-hidden="true">{a.ok ? "ok" : "!!"}</span> {a.name}
                    </li>
                  ))}
                </ul>
                <p className="note note--tight">
                  The same assertions run in node with <code>npm run selfcheck</code>, which also
                  scans the simulation modules for wall-clock time and unseeded randomness.
                </p>
              </>
            ) : (
              <p className="note note--tight">Runs once the replay finishes.</p>
            )}
          </div>
        </div>
      </div>
    </Section>
  );
}
