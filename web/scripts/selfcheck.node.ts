/* Node entry for the self-check: loads the fixture files from disk (Vite's ?raw imports are not
   available here) and prints the same tables the CLI prints. */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ProcedureFixture } from "../src/fixtures";
import { selfCheck } from "../src/sim/selfcheck";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "fixtures");
const read = (dir: string, name: string) => readFileSync(join(root, dir, name), "utf8");

const fixtures: ProcedureFixture[] = [
  {
    dir: "support_triage",
    label: "Support triage",
    sop: read("support_triage", "sop.md"),
    walkthrough: read("support_triage", "walkthrough.md"),
    rubricYaml: read("support_triage", "rubric.yaml"),
    scenariosYaml: read("support_triage", "scenarios.yaml"),
    kb: JSON.parse(read("support_triage", "kb.json")),
  },
  {
    dir: "incident_comms",
    label: "Incident communications",
    sop: read("incident_comms", "sop.md"),
    walkthrough: read("incident_comms", "walkthrough.md"),
    rubricYaml: read("incident_comms", "rubric.yaml"),
    scenariosYaml: read("incident_comms", "scenarios.yaml"),
    kb: [],
  },
];

const result = selfCheck(fixtures);
console.log(result.lines.join("\n"));
process.exit(result.ok ? 0 : 1);
