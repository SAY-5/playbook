/* Node entry for the self-check: loads the procedure files from ../../procedures (Vite's ?raw
   imports are not available here), reads the simulation modules so the purity assertions can scan
   them, and prints the same tables the CLI prints. Exits non-zero on the first failed assertion. */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ProcedureFixture } from "../src/fixtures";
import { selfCheck, type SourceFile } from "../src/sim/selfcheck";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..", "procedures");
const simDir = join(here, "..", "src", "sim");
const read = (dir: string, name: string) => readFileSync(join(dir, name), "utf8");

const fixtures: ProcedureFixture[] = [
  {
    dir: "support_triage",
    label: "Support triage",
    sop: read(join(root, "support_triage"), "sop.md"),
    walkthrough: read(join(root, "support_triage"), "walkthrough.md"),
    rubricYaml: read(join(root, "support_triage"), "rubric.yaml"),
    scenariosYaml: read(join(root, "support_triage"), "scenarios.yaml"),
    kb: JSON.parse(read(join(root, "support_triage"), "kb.json")),
  },
  {
    dir: "incident_comms",
    label: "Incident communications",
    sop: read(join(root, "incident_comms"), "sop.md"),
    walkthrough: read(join(root, "incident_comms"), "walkthrough.md"),
    rubricYaml: read(join(root, "incident_comms"), "rubric.yaml"),
    scenariosYaml: read(join(root, "incident_comms"), "scenarios.yaml"),
    kb: [],
  },
];

const sources: SourceFile[] = readdirSync(simDir)
  .filter((name) => name.endsWith(".ts") && name !== "selfcheck.ts")
  .sort()
  .map((name) => ({ name: `sim/${name}`, text: read(simDir, name) }));

const result = selfCheck(fixtures, sources);
console.log(result.lines.join("\n"));
process.exit(result.ok ? 0 : 1);
