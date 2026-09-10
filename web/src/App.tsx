import { useMemo, useState } from "react";
import { Footer, TopBar } from "./components/Chrome";
import { Corrections } from "./components/Corrections";
import { EvalGrid } from "./components/EvalGrid";
import { FullRun } from "./components/FullRun";
import { Hero } from "./components/Hero";
import { Transcript } from "./components/Transcript";
import { FIXTURES } from "./fixtures";
import { computeArc } from "./sim/arc";

export default function App() {
  const [dir, setDir] = useState(FIXTURES[0].dir);
  const arcs = useMemo(() => new Map(FIXTURES.map((f) => [f.dir, computeArc(f)])), []);
  const arc = arcs.get(dir) ?? arcs.get(FIXTURES[0].dir)!;
  const runs = arc.rounds.reduce((total, round) => total + round.outcomes.length, 0);

  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <TopBar fixtures={FIXTURES} active={dir} onSelect={setDir} />
      <main id="main">
        <span id="top" />
        <Hero arc={arc} runs={runs} />
        <Transcript arc={arc} />
        <EvalGrid arc={arc} />
        <Corrections arc={arc} />
        <FullRun arc={arc} />
      </main>
      <Footer />
    </>
  );
}
