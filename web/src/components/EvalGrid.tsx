/* Evaluation grid: every scenario against every prompt version, red to green. The focused column
   is the one the segmented control selects; the others stay legible but recede. */
import { useEffect, useMemo, useState } from "react";
import { verdict, type Arc } from "../sim/arc";
import { pct } from "../sim/report";
import { Section } from "./Section";

export interface EvalGridProps {
  arc: Arc;
}

export function EvalGrid({ arc }: EvalGridProps) {
  const [focus, setFocus] = useState(arc.rounds.length - 1);
  useEffect(() => setFocus(arc.rounds.length - 1), [arc]);

  const scenarios = useMemo(() => arc.workspace.scenarios.scenarios, [arc]);
  const focused = arc.rounds[focus];
  const newlyPassing = new Set(focused?.comparison?.newlyPassing ?? []);

  return (
    <Section
      id="evaluation"
      num="02"
      title="Every scenario, every version"
      lede={
        <>
          Each run is scored against the expert rubric: weighted criteria for required and
          forbidden actions, tool ordering, ticket fields and a judged rationale. A scenario passes
          only when it clears the rubric&rsquo;s threshold with no forbidden action. Below is the whole
          set, one column per prompt version.
        </>
      }
      aside={
        <div className="seg" role="group" aria-label="focus prompt version">
          {arc.rounds.map((r, i) => (
            <button key={r.spec.version} type="button" className="seg__btn" aria-pressed={focus === i} onClick={() => setFocus(i)}>
              v{r.spec.version}
            </button>
          ))}
        </div>
      }
    >
      <div className="gridpanel glass">
        <div className="gridpanel__summary" role="status" aria-live="polite">
          <strong>v{focused?.spec.version}</strong> passes {focused?.report.passed} of {arc.scenarios} scenarios (
          {pct(focused?.report.passRate ?? 0)}), mean score {pct(focused?.report.meanScore ?? 0)},{" "}
          {focused?.report.forbiddenViolations} forbidden action
          {focused?.report.forbiddenViolations === 1 ? "" : "s"}
          {newlyPassing.size > 0 ? `, ${newlyPassing.size} newly passing` : ""}.
        </div>
        <div className="scroll-x">
          <table className="tbl grid">
            <caption className="sr-only">Pass or fail for each scenario under each prompt version</caption>
            <thead>
              <tr>
                <th scope="col">scenario</th>
                <th scope="col" className="grid__intake">
                  intake
                </th>
                {arc.rounds.map((r, i) => (
                  <th key={r.spec.version} scope="col" className={i === focus ? "is-focus" : ""}>
                    v{r.spec.version}
                    <span className="grid__rate">{pct(r.report.passRate)}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {scenarios.map((sc) => (
                <tr key={sc.id}>
                  <th scope="row">{sc.id}</th>
                  <td className="grid__intake">{sc.tags.join(" ") || Object.values(sc.intake).slice(1, 3).join(" ")}</td>
                  {arc.rounds.map((r, i) => {
                    const passed = verdict(arc, i, sc.id);
                    const isNew = i === focus && newlyPassing.has(sc.id);
                    return (
                      <td key={r.spec.version} className={i === focus ? "is-focus" : "is-dim"}>
                        <span className={`cell ${passed ? "cell--pass" : "cell--fail"}${isNew ? " cell--new" : ""}`}>
                          {passed ? "pass" : "fail"}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="gridpanel glass gridpanel--table">
        <h3 className="panel__title">Before and after, as the CLI prints it</h3>
        <div className="scroll-x">
          <pre className="mono-block">{arc.table}</pre>
        </div>
      </div>
    </Section>
  );
}
