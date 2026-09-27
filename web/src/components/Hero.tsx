/* Opening section: what the pipeline is, and the figures this page measured while loading. */
import type { ReactNode } from "react";
import type { Arc } from "../sim/arc";
import { pct } from "../sim/report";
import { Counter } from "./Counter";

const STAGES = ["sop.md + walkthrough.md", "ingest", "prompt vN", "tool loop", "rubric grade", "corrections"];

export interface HeroProps {
  arc: Arc;
  runs: number;
}

export function Hero({ arc, runs }: HeroProps) {
  const first = arc.passRates[0];
  const last = arc.passRates[arc.passRates.length - 1];
  const rounds = arc.rounds.length - 1;
  const spoken =
    `${arc.label}: pass rate ${pct(first)} on prompt v1, ${pct(last)} after ${rounds} correction ` +
    `${rounds === 1 ? "round" : "rounds"}, ${arc.corrections.length} corrections, ${runs} graded runs.`;

  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="wrap hero__inner">
        <p className="hero__eyebrow">
          <span className="chip chip--mode">offline</span>
          <span className="chip">deterministic stand-in</span>
          <span className="chip">no API key</span>
        </p>
        <h1 className="hero__title" id="hero-title">
          An expert&rsquo;s procedure, compiled into an agent that is{" "}
          <em>graded against the expert&rsquo;s own rubric</em> and corrected from its failures.
        </h1>
        <p className="hero__lede">
          Playbook parses a standard operating procedure and a walkthrough into a cited{" "}
          <code>Procedure</code>, renders a versioned system prompt from it, runs a bounded
          tool-calling loop against Jira, Slack and a knowledge base, scores every run against the
          expert&rsquo;s rubric, and turns the failures back into explicit prompt rules. This page runs
          that whole loop in your browser, on the same fixtures and the same rules the Python
          offline mode uses.
        </p>

        <div className="hero__stats">
          <Stat label="pass rate, prompt v1" value={<Counter value={first * 100} decimals={1} suffix="%" />} tone="fail" />
          <Stat label={`pass rate, prompt v${arc.rounds.length}`} value={<Counter value={last * 100} decimals={1} suffix="%" duration={1400} />} tone="pass" />
          <Stat label="corrections derived" value={<Counter value={arc.corrections.length} duration={1200} />} />
          <Stat label="graded runs" value={<Counter value={runs} duration={1600} />} />
        </div>
        <p className="sr-only" role="status" aria-live="polite">
          {spoken}
        </p>

        <p className="hero__cta">
          <a className="btn btn--primary" href="#run">
            Replay the whole arc
          </a>
          <a className="btn" href="#transcript">
            Step through a transcript
          </a>
        </p>

        <ol className="pipeline" aria-label="pipeline stages">
          {STAGES.map((stage) => (
            <li key={stage} className="pipeline__stage">
              {stage}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "pass" | "fail" }) {
  return (
    <div className={`stat${tone ? ` stat--${tone}` : ""}`}>
      <span className="stat__value">{value}</span>
      <span className="stat__label">{label}</span>
    </div>
  );
}
