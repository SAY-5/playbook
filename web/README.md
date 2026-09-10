# Browser demo

A static page that runs the Playbook offline pipeline in the browser: ingest, prompt versions,
the tool-calling loop, the rubric grader and the correction loop. No backend, no network calls,
no API key. Vite, React 18 and TypeScript in strict mode.

`src/sim/` is a port of the Python offline path, module for module:

| module | ports |
|---|---|
| `ingest.ts` | `playbook/ingest`: SOP and walkthrough parsing with citations |
| `prompt.ts` | `playbook/agent/prompt.py`: versioned `PromptSpec` rendering and correction merging |
| `engine.ts` | `fakes/model_server.py`: the deterministic stand-in and its rule grammar |
| `tools.ts` | `fakes/jira_server.py`, `fakes/slack_server.py`, the knowledge base and the tool schemas |
| `loop.ts` | `playbook/agent/loop.py`: the bounded tool loop and the run trace |
| `grader.ts`, `scenarios.ts` | `playbook/evals`: rubrics, scenario sets, criteria and the offline judge |
| `corrections.ts`, `feedback.ts` | `playbook/feedback`: correction derivation and the improvement loop |
| `report.ts` | `playbook/evals/report.py`, including Python's half-to-even percent formatting |
| `arc.ts` | the whole run for one procedure, plus the summary block |

The simulation is deterministic: ids and simulated latencies come from a seeded PRNG
(`prng.ts`), there is no `Math.random`, no wall-clock time and no `eval`, and the self-check
asserts all three by scanning the modules.

## Commands

```
npm install
npm run dev         # local dev server
npm run bundle      # type-check and produce dist/ (alias of the build script Vercel runs)
npm run selfcheck   # 47 assertions in node, exits non-zero on any failure
npm run preview     # serve dist/
```

`npm run selfcheck` reproduces the measured results in the repository README: support triage
12.5% -> 87.5% -> 100.0% over three prompt versions with 12 corrections, incident communications
12.5% -> 100.0% with 6, and asserts that the same seed produces an identical summary while a
different seed changes run ids without changing a single grade.

## Sections

1. **One run, turn by turn** steps through a single scenario's trace: intake, each model turn with
   its stop reason and token counts, each tool call with its arguments and the JSON returned.
2. **Every scenario, every version** grades the whole set against every prompt version, red to
   green, with the before and after table the CLI prints.
3. **What each round changed** lists the corrections a round derived, the SOP step each was
   appended to, the criterion that failed and the scenarios that produced it.
4. **Run the whole arc** replays the loop's log, then prints the summary block and the self-check
   result.

## Deployment

`vercel.json` builds with `npm run build` into `dist/`. The page is entirely static.
