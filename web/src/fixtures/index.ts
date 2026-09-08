/* Sample procedures copied verbatim from ../../procedures in the repository root. */
import stSop from "./support_triage/sop.md?raw";
import stWalk from "./support_triage/walkthrough.md?raw";
import stRubric from "./support_triage/rubric.yaml?raw";
import stScenarios from "./support_triage/scenarios.yaml?raw";
import stKb from "./support_triage/kb.json";
import icSop from "./incident_comms/sop.md?raw";
import icWalk from "./incident_comms/walkthrough.md?raw";
import icRubric from "./incident_comms/rubric.yaml?raw";
import icScenarios from "./incident_comms/scenarios.yaml?raw";
import type { KbArticle } from "../sim/types";

export interface ProcedureFixture {
  dir: string;
  label: string;
  sop: string;
  walkthrough: string;
  rubricYaml: string;
  scenariosYaml: string;
  kb: KbArticle[];
}

export const FIXTURES: ProcedureFixture[] = [
  {
    dir: "support_triage",
    label: "Support triage",
    sop: stSop,
    walkthrough: stWalk,
    rubricYaml: stRubric,
    scenariosYaml: stScenarios,
    kb: stKb as KbArticle[],
  },
  {
    dir: "incident_comms",
    label: "Incident communications",
    sop: icSop,
    walkthrough: icWalk,
    rubricYaml: icRubric,
    scenariosYaml: icScenarios,
    kb: [],
  },
];

export function fixture(dir: string): ProcedureFixture {
  const f = FIXTURES.find((x) => x.dir === dir);
  if (!f) throw new Error(`unknown procedure ${dir}`);
  return f;
}
