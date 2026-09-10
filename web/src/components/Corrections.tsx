/* Corrections panel: what each round appended to the prompt and what it bought. A correction is
   derived from a failed rubric criterion, conditioned on the smallest set of scenario facts that
   separates the failures from the scenarios expecting something else. */
import { type Arc } from "../sim/arc";
import { pct } from "../sim/report";
import type { Correction } from "../sim/types";
import { Section } from "./Section";

export interface CorrectionsProps {
  arc: Arc;
}

export function Corrections({ arc }: CorrectionsProps) {
  const byVersion = new Map<number, Correction[]>();
  for (const c of arc.corrections) {
    const list = byVersion.get(c.version) ?? [];
    list.push(c);
    byVersion.set(c.version, list);
  }
  const versions = Array.from(byVersion.keys()).sort((a, b) => a - b);

  return (
    <Section
      id="corrections"
      num="03"
      title="What each round changed"
      lede={
        <>
          A failed criterion carries a remediation template naming the SOP step it belongs to. The
          loop fills the template from the run&rsquo;s own evidence and conditions it on the facts that
          distinguish the failing scenarios, then appends the rule under that step in the next
          prompt version. Nothing is invented: every line below is traceable to a graded failure.
        </>
      }
    >
      <div className="rounds">
        {versions.map((version) => {
          const round = arc.rounds.find((r) => r.spec.version === version);
          const before = arc.rounds.find((r) => r.spec.version === version - 1);
          const items = byVersion.get(version) ?? [];
          return (
            <article className="round glass" key={version} aria-labelledby={`round-v${version}`}>
              <header className="round__head">
                <h3 className="round__title" id={`round-v${version}`}>
                  v{version - 1} &rarr; v{version}
                </h3>
                <p className="round__delta">
                  <span className="chip chip--fail">{pct(before?.report.passRate ?? 0)}</span>
                  <span className="round__arrow" aria-hidden="true">
                    &rarr;
                  </span>
                  <span className="chip chip--pass">{pct(round?.report.passRate ?? 0)}</span>
                  <span className="chip chip--accent">
                    {items.length} correction{items.length === 1 ? "" : "s"}
                  </span>
                </p>
              </header>
              <ul className="round__list">
                {items.map((c) => (
                  <li className="correction" key={`${c.stepId}-${c.text}`}>
                    <p className="correction__meta">
                      <span className="chip">{c.stepId}</span>
                      <span className="chip">{c.criterion}</span>
                    </p>
                    <p className="correction__text">{c.text}</p>
                    <p className="correction__evidence">{c.evidence}</p>
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>
      <p className="note">
        Stopped after v{arc.rounds.length}: {arc.stopReason}. The loop keeps every version, so a
        correction that helps one criterion and breaks another shows up as a regression in the
        before and after table rather than disappearing.
      </p>
    </Section>
  );
}
