# Changelog

## v6.0.0 (unreleased)

Breaking: the run store lays every artifact out under one root keyed by the procedure slug
(`<slug>/prompts`, `reports`, `traces`, `grades`, `bank.json`, `proposals`, `promotions`), on disk
and in S3 alike. Runs directories written by earlier versions are not read.

- Prompt versions, graded reports, per-run grades and the scenario bank go through the run store,
  so `PLAYBOOK_RUN_STORE=s3` holds everything and the Lambda runner can load any stored version.
  The DynamoDB run item carries the grade's score and verdict.
- The Lambda handler defaults to the promoted version when the message names none and refuses a
  procedure with no promoted version.
- `make lambda-zip` resolves the bundle for the Lambda platform (x86_64 manylinux, python 3.12)
  from `uv.lock` on any host; `make lambda-check` imports it under that platform in Docker, and CI
  imports it on ubuntu. The function declares `architectures = ["x86_64"]` rather than relying on
  the AWS default, so a change of default cannot leave it with a bundle it cannot load.
- `serve-fakes --host` binds a chosen address; the compose fakes service binds `0.0.0.0` so its
  published ports work.
- Live mode requires `JIRA_BASE_URL`, `JIRA_TOKEN` and `SLACK_TOKEN` unless `PLAYBOOK_TOOLS=fake`
  asks for the local stand-ins; every trace records the Jira and Slack hosts it used.
- Ingest no longer treats any sentence containing "is" as a decision; priority matrices are
  detected as such, and decisions are linked to steps by the channel or tool they name before
  keyword overlap.
- `playbook review propose` records a reviewer-authored rule as a proposal, which is how
  `make demo-review` builds the deliberately regressed v4 the guard catches.
- `playbook loop` reports "all scenarios pass" when the last permitted round gets there, and a
  round that lifts a scenario is not a plateau.
- The `regress` artifact carries the replayed version's scores in `versions`.
- `playbook ops` reads the run store, so it works against S3 as well as a local directory.
- The Docker image installs from `uv.lock` with a pinned uv release.
- `__version__` comes from the installed package metadata.
- `make demo-review` runs the promotion gate, the audit trail, the scenario bank and both
  regression runs on the output of `make demo`, so every figure in the README has a command
  behind it.
- Browser demo: the fonts are served with the page, and both faces are under the SIL Open Font
  License 1.1 with the license text committed beside them; the display face is the latin subset of
  Space Grotesk. The rubrics and scenario sets are parsed at build time, and framer-motion and
  `yaml` are gone from the bundle, which halves its JavaScript: 227.58 kB against 449.19 kB
  measured at 9405f90, the last commit on this branch that still bundled them (73.29 kB against
  144.20 kB gzipped). Section reveals are CSS driven by one IntersectionObserver hook, so
  `prefers-reduced-motion` is honoured everywhere on the page.
- Browser demo: the transcript has a second rail tab listing the rules the stand-in parsed out of
  each prompt version with their conditions, the correction that added each one, and the prose it
  ignored; percentages are rounded the way Python rounds them, checked against a generated table.
- CI runs the browser demo's type-check, its 51 self-check assertions, the production bundle and a
  Chrome smoke test that fails on a console error, an off-origin request or horizontal overflow.

## v5.0.0 (2026-09-10)

- `playbook ops` summarises a runs directory: procedures, prompt versions, pass rate history, open
  forbidden actions with the criteria that failed, pending proposals, the promoted version, and the
  last run with its duration.
- `eval`, `loop` and `regress` each write a JSON artifact under `runs/<procedure>/artifacts/` with
  the version scores, the failing scenarios and the measured cost of the run.
- Tool-call counts per tool, calls per run, tool latency (mean, p95, max) and run wall time are
  measured from the traces; each trace now records its own duration.
- `make demo` prints the ops summary at the end.

## v4.0.0 (2026-09-10)

- `playbook bank` keeps every scenario a procedure has been run on, with its tags and how each
  prompt version scored it, merging in `scenarios.yaml` and any other set on each call.
- `playbook regress` replays the bank against a version, compares each scenario with the last
  version that scored it, and exits non-zero when a previously passing scenario breaks.
- New scenarios the bank has never scored are reported apart from regressions, and pass rates are
  reported per tag. `--tag` and `--failures` narrow the replay.

## v3.0.0 (2026-09-10)

- Every derived correction is a proposal a reviewer approves, edits or rejects before it enters a
  prompt version (`playbook review list|approve|edit|reject|report`); the unattended loop decides
  as the reviewer `auto`, and `playbook loop --review` hands the queue to an expert instead.
- `playbook diff` compares two versions step by step, reporting steps added, removed and changed,
  including retitled and reordered steps.
- `playbook promote` signs a graded version off for use and refuses while the version commits a
  forbidden action or carries undecided proposals.
- `playbook review audit` prints the decision trail, corrections and versions together. Proposals
  and promotions are stored with the runs, on disk or in S3 with a DynamoDB index.

## v2.0.0 (2026-09-08)

- Decision-branch and rubric coverage for scenario sets (`playbook coverage`), flagging
  procedures with uncovered branches or one-sided criteria.
- Scenario synthesis from walkthrough decision points (`playbook synthesize`), one scenario per
  branch with inferred or expert-flagged expectations; `eval --scenarios` runs any set.

## v1.0.0 (2026-09-08)

- Ingest with citations, versioned PromptSpec, tool-calling loop over the Messages API with the
  offline stand-in, rubric grader, feedback loop, run store and the Terraform stack.
