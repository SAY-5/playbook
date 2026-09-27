/* The sample procedures under ../../procedures in the repository root, read at build time through
   the @procedures alias in vite.config.ts, so the page and the Python CLI run the same files. */
import stSop from "@procedures/support_triage/sop.md?raw";
import stWalk from "@procedures/support_triage/walkthrough.md?raw";
import stRubric from "@procedures/support_triage/rubric.yaml?raw";
import stScenarios from "@procedures/support_triage/scenarios.yaml?raw";
import stKb from "@procedures/support_triage/kb.json";
import icSop from "@procedures/incident_comms/sop.md?raw";
import icWalk from "@procedures/incident_comms/walkthrough.md?raw";
import icRubric from "@procedures/incident_comms/rubric.yaml?raw";
import icScenarios from "@procedures/incident_comms/scenarios.yaml?raw";
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
