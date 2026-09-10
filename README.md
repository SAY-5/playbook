# Playbook

Expert SOP to deployed agent, with evals. Playbook ingests an expert's walkthrough and standard
operating procedure into a tool-calling agent on the Anthropic API with Jira and Slack tools,
grades the agent's runs against the expert's rubric, feeds the failures back into the prompt as
explicit corrections, and deploys the runner on AWS with Terraform.

```
 sop.md -----+                                 Messages API
             +--> ingest --> prompt vN --------------------> tool loop --> jira.* slack.* kb.search
 walkthrough +    (citations)     ^                              |
                                  |                              v  RunTrace (every turn and tool call)
                            corrections <-- feedback <-- grader (rubric.yaml) --> S3 + DynamoDB | disk
                                            (vN+1, re-run, before/after table)
```

## What it does

- **Ingest** parses `sop.md` (numbered steps with tools, preconditions, escalation rules,
  prohibitions) and `walkthrough.md` (a transcript) into a structured `Procedure`. Every step,
  rule and decision point cites the file and line it came from.
- **Agent** renders a versioned system prompt from the Procedure and runs a bounded tool-calling
  loop over the Anthropic Messages API (default model `claude-sonnet-5`, override with
  `PLAYBOOK_MODEL`) with `jira.create_issue`, `jira.transition`, `jira.comment`, `slack.post`,
  `slack.lookup_channel` and `kb.search`. Each run produces a trace of every model turn and tool
  call, stored on disk or in S3 with a DynamoDB index.
- **Evals** grade runs against an expert rubric (YAML): weighted criteria, required and forbidden
  actions, ordering, ticket field checks, plus a judged rationale. Reports are produced per run
  and per prompt version with regression comparison.
- **Feedback** turns failed criteria into explicit rules appended to the relevant SOP step,
  creates the next prompt version, re-runs the scenario set and records the before/after delta.
  `playbook loop` iterates until the pass rate plateaus; every version is kept.
- **Review** holds each derived rule as a proposal an expert approves, edits or rejects, diffs the
  steps between two versions, and refuses to promote a version that still commits a forbidden
  action. Every decision is kept next to the runs as an audit trail.
- **Regression safety** banks every scenario with its tags and per-version outcomes, replays the
  bank against a new version, and fails the run when a scenario that used to pass breaks. Pass
  rates are reported per tag.
- **Deploy** with Terraform: S3 artifact bucket, SQS run queue with dead-letter queue, DynamoDB
  run index, Secrets Manager for API keys, and a Lambda runner. The same stack applies against
  LocalStack.

## Offline and live modes

No API key or AWS account is needed to run everything in this repository.

| | offline (default) | `--live` |
|---|---|---|
| model | `fakes/model_server.py`: a deterministic stand-in that speaks the Messages API request and response shape, including `tool_use` and `tool_result` turns, used through the official `anthropic` SDK with `base_url` | Anthropic Messages API with `ANTHROPIC_API_KEY` |
| Jira, Slack | `fakes/jira_server.py`, `fakes/slack_server.py` with inspectable inboxes | real APIs via `JIRA_BASE_URL`, `JIRA_TOKEN`, `SLACK_TOKEN` |
| judge | transparent heuristic | model-graded rationale |
| run store | local disk, or S3 and DynamoDB on LocalStack | S3 and DynamoDB |

The offline model follows the SOP steps in the system prompt in order, but only honours
instructions phrased as explicit rules (`When severity is sev1, post to #oncall-sev1 mentioning
the issue key.`). Prose it cannot parse is ignored, so prompt corrections genuinely change what
the next run does. The grammar is documented in [ARCHITECTURE.md](ARCHITECTURE.md).

All numbers below come from `make demo` in offline mode on this machine. No live run has been
performed; the live path is exercised by `tests/test_live.py`, which is skipped without
`ANTHROPIC_API_KEY`.

## Quick start

```
make setup        # uv sync, Python 3.12
make demo         # offline: serve fakes, ingest, run 24 scenarios, grade, improve, print tables
make lint test tf-validate
```

`make demo` serves the fakes, ingests both sample procedures, builds prompt v1, runs the
scenario sets (16 support triage requests, 8 incident reports), grades them against the rubrics,
runs the feedback loop until every scenario passes or the pass rate plateaus, and prints the
before/after tables and the Jira and Slack inbox evidence.

## Measured results (offline mode)

Support triage, 16 scenarios. v1 is the prompt rendered straight from the SOP and walkthrough;
v2 and v3 add the corrections derived from the graded failures.

```
support-triage: 16 scenarios, mode=offline
| metric                    | v1     | v2     | v3     | delta v1 to v3 |
|---------------------------|--------|--------|--------|----------------|
| pass rate                 | 12.5%  | 87.5%  | 100.0% | +87.5%         |
| mean score                | 80.1%  | 98.9%  | 100.0% | +19.9%         |
| required-action coverage  | 100.0% | 100.0% | 100.0% | +0.0%          |
| forbidden actions         | 2      | 2      | 0      | -2             |
|   kb_searched             | 100.0% | 100.0% | 100.0% | +0.0%          |
|   kb_before_ticket        | 100.0% | 100.0% | 100.0% | +0.0%          |
|   ticket_in_sup           | 100.0% | 100.0% | 100.0% | +0.0%          |
|   summary_prefixed        | 0.0%   | 100.0% | 100.0% | +100.0%        |
|   priority_matches_matrix | 12.5%  | 100.0% | 100.0% | +87.5%         |
|   findings_commented      | 100.0% | 100.0% | 100.0% | +0.0%          |
|   escalated_when_required | 43.8%  | 100.0% | 100.0% | +56.2%         |
|   oncall_paged_for_sev1   | 75.0%  | 100.0% | 100.0% | +25.0%         |
|   no_pii_in_slack         | 87.5%  | 87.5%  | 100.0% | +12.5%         |
|   never_done              | 100.0% | 100.0% | 100.0% | +0.0%          |
|   final_state             | 100.0% | 100.0% | 100.0% | +0.0%          |
|   run_quality             | 100.0% | 100.0% | 100.0% | +0.0%          |
stopped: all scenarios pass
```

Corrections the loop derived (each is appended under the named SOP step in the next version):

```
v2 [create-ticket] Set summary to "[{severity}] {title}".
v2 [create-ticket] When severity is sev1, set priority to "Highest".
v2 [create-ticket] When severity is sev2 and tier is enterprise, set priority to "Highest".
v2 [create-ticket] When severity is sev2 and tier is pro, set priority to "High".
v2 [create-ticket] When severity is sev2 and tier is free, set priority to "High".
v2 [create-ticket] When severity is sev3 and tier is enterprise, set priority to "High".
v2 [create-ticket] When severity is sev4, set priority to "Low".
v2 [escalate] When severity is sev1, post to #support-escalations mentioning the issue key.
v2 [escalate] When tier is enterprise, post to #support-escalations mentioning the issue key.
v2 [escalate] When severity is sev1, post to #oncall-sev1 mentioning the issue key.
v2 [escalate] When posting to Slack, do not include the customer email.
v3 [escalate] When posting to Slack, do not include the customer phone number.
```

The v3 correction is the loop working as intended: the v2 rule stopped email leaks, which let the
Enterprise escalations run, which exposed the phone-number leak in two scenarios that had not
escalated before.

Incident communications, 8 scenarios:

```
incident-communications: 8 scenarios, mode=offline
| metric                                | v1     | v2     | delta v1 to v2 |
|---------------------------------------|--------|--------|----------------|
| pass rate                             | 12.5%  | 100.0% | +87.5%         |
| mean score                            | 83.3%  | 100.0% | +16.7%         |
| required-action coverage              | 100.0% | 100.0% | +0.0%          |
| forbidden actions                     | 0      | 0      | +0             |
|   channel_looked_up                   | 100.0% | 100.0% | +0.0%          |
|   lookup_before_ticket                | 100.0% | 100.0% | +0.0%          |
|   ticket_in_inc                       | 100.0% | 100.0% | +0.0%          |
|   summary_prefixed                    | 0.0%   | 100.0% | +100.0%        |
|   priority_matches_matrix             | 25.0%  | 100.0% | +75.0%         |
|   announced_in_incidents              | 100.0% | 100.0% | +0.0%          |
|   owners_notified                     | 100.0% | 100.0% | +0.0%          |
|   comms_logged                        | 100.0% | 100.0% | +0.0%          |
|   status_updates_when_customer_facing | 50.0%  | 100.0% | +50.0%         |
|   ic_paged_for_full_outage            | 75.0%  | 100.0% | +25.0%         |
|   not_resolved_in_first_post          | 100.0% | 100.0% | +0.0%          |
|   never_general                       | 100.0% | 100.0% | +0.0%          |
|   run_quality                         | 100.0% | 100.0% | +0.0%          |
stopped: all scenarios pass
```

Evidence from the fake inboxes after the last version (excerpt):

```
Jira inbox: 8 issues
  INC-101 [Highest] [full outage] Payments API returning 503 for all requests -> Open (1 comment)
  INC-102 [High] [partial outage] Login failing for EU region users -> Open (1 comment)
Slack inbox: 22 messages
  #incidents: INC-101: [full outage] Payments API returning 503 for all requests Status: investigating.
  #ic-oncall: INC-101: [full outage] Payments API returning 503 for all requests Status: investigating.
  #team-payments: INC-101: [full outage] Payments API returning 503 for all requests Status: investigating.
  #status-updates: INC-101: [full outage] Payments API returning 503 for all requests Status: investigating.
```

These figures describe the offline stand-in, whose gaps are by construction. A live model reads
the SOP prose far better than the stand-in, so a live v1 should start higher; the pipeline,
rubric and corrections are the same in both modes.

### Browser demo

`web/` is a static page that runs this same offline pipeline in the browser: the tool-calling
loop, the rubric grader and the correction loop, with a transcript viewer, the evaluation grid
and a replay of the whole arc. It is a port of the offline path rather than a recording, so
`npm run selfcheck` in that directory reproduces the tables above from 47 assertions. See
[web/README.md](web/README.md).

## CLI

```
playbook ingest PROCEDURE_DIR                  parse sop.md and walkthrough.md, write procedure.json
playbook run PROCEDURE_DIR [--scenario ID]     run the agent on the scenario set, store traces
playbook eval PROCEDURE_DIR [--compare N]      run and grade a prompt version, print the report
playbook improve PROCEDURE_DIR [--dry-run]     derive corrections from the last report, create vN+1
playbook loop PROCEDURE_DIR [--max-rounds N]   run, grade, correct and re-run until plateau
playbook review list|approve|edit|reject       decide the proposals derived from a version
playbook review report|audit PROCEDURE_DIR     per-version review counts; the full decision trail
playbook diff PROCEDURE_DIR [--from N --to M]  steps added, removed and changed between versions
playbook promote PROCEDURE_DIR [--version N]   sign a version off, refused while the gate blocks
playbook report PROCEDURE_DIR [--inbox]        before/after table from stored reports
playbook coverage PROCEDURE_DIR [--strict]     decision-branch and rubric coverage of the scenario set
playbook synthesize PROCEDURE_DIR [--only-uncovered]  one scenario per walkthrough decision branch
playbook bank PROCEDURE_DIR [--add FILE]       the scenario bank: every scenario, its tags, its outcomes
playbook regress PROCEDURE_DIR [--tag T]       replay the bank against a version, guard the result
playbook serve-fakes                           serve the offline model, Jira and Slack stand-ins
```

Every command accepts `--runs-dir` (or `PLAYBOOK_RUNS_DIR`); `run`, `eval` and `loop` accept
`--live`; `eval` and `coverage` accept `--scenarios FILE` to use another scenario set, for example
the synthesized one. A procedure directory contains `sop.md`, `walkthrough.md`, `rubric.yaml`,
`scenarios.yaml` and optionally `kb.json`; see `procedures/`.

Environment: `PLAYBOOK_MODEL`, `ANTHROPIC_API_KEY`, `JIRA_BASE_URL`, `JIRA_TOKEN`, `SLACK_TOKEN`,
`PLAYBOOK_RUN_STORE=local|s3`, `PLAYBOOK_S3_BUCKET`, `PLAYBOOK_DDB_TABLE`, `AWS_ENDPOINT_URL`
(LocalStack), `PLAYBOOK_MAX_STEPS`.

## Review and approval

A correction the loop derives is a proposal until someone decides on it. `playbook review list`
shows the pending ones with the criterion and the scenarios that failed; `approve`, `edit --text`
and `reject` record the decision under the reviewer's name (`--as`, `PLAYBOOK_REVIEWER` or the
login name). Only approved proposals enter the next version, with the edited wording when there is
one. `playbook loop` and `playbook improve --auto-approve` decide as the reviewer `auto`, so the
unattended path is unchanged; `playbook loop --review` stops and hands the queue over instead.

`playbook diff` compares two versions step by step, which is what a reviewer reads before signing
off:

```
support-triage v2 to v3: 0 step(s) added, 0 removed, 1 changed, 4 unchanged
  changed [escalate] Escalate when needed
    + When posting to Slack, do not include the customer phone number.
  unchanged: kb-search, create-ticket, record-findings, set-state
```

`playbook promote` signs a graded version off for use. The gate refuses while the version still
commits a forbidden action or while proposals from it are undecided, and the refusal is recorded
too:

```
$ playbook promote procedures/support_triage --version 1 --as dana
v1 blocked by dana at 2026-09-10T08:51:52+00:00
  blocked by forbidden-action: no_pii_in_slack in 2 scenario(s): triage-01, triage-03
$ playbook promote procedures/support_triage --as dana --note "phone and email leaks cleared"
v3 promoted by dana at 2026-09-10T08:51:53+00:00 (pass rate 100%, 0 forbidden action(s))
```

`playbook review audit` prints every decision in order, corrections and versions together (4 of
the 14 lines of that run):

```
support-triage audit trail: 14 decision(s) by auto, dana
  2026-09-10T08:51:50+00:00  auto       approved  p1-01    [create-ticket] Set summary to "[{severity}] {title}". (applied in v2)
  2026-09-10T08:51:51+00:00  auto       approved  p2-01    [escalate] When posting to Slack, do not include the customer phone number. (applied in v3)
  2026-09-10T08:51:52+00:00  dana       blocked   v1       forbidden-action: no_pii_in_slack in 2 scenario(s): triage-01, triage-03
  2026-09-10T08:51:53+00:00  dana       promoted  v3       pass rate 100% note: phone and email leaks cleared
```

Proposals and promotions are stored with the runs, on disk or in S3 with a DynamoDB index.

## Scenario coverage and synthesis

`playbook coverage` splits every walkthrough decision point into the branches an expert would
test (each severity, tier or impact level it names, both sides of a KB match or customer-facing
condition, and an `otherwise` branch when only some values are named) and reports which scenarios
cover each one, plus how many scenarios exercise each rubric criterion and on which side. A
procedure with an uncovered branch or a one-sided criterion is flagged; `--strict` turns that
into a non-zero exit. Both sample sets cover all of their branches (11 for support triage, 8 for
incident communications), measured offline:

```
support-triage coverage: 16 scenarios, 4 branching decisions, 11/11 branches covered (100.0%)
  d2 [escalate] One exception: Enterprise accounts get bumped one level for sev2 and sev3, ... (walkthrough.md:8)
    ok  severity=sev2 and tier=enterprise                triage-05, triage-08
    ok  severity=sev3 and tier=enterprise                triage-09, triage-12
    ok  otherwise (severity=sev1 and tier=pro)           triage-01, triage-02, triage-03, triage-04 +8
criteria:
  escalated_when_required                 16 scenario(s) expected=9 not_expected=7
flagged: none
```

`playbook synthesize` writes `runs/<procedure>/scenarios.synth.yaml` with one new scenario per
branch (or per uncovered branch with `--only-uncovered`). Each takes the closest hand-written
scenario as a template, writes the branch values into the intake, and infers expected outcomes
from existing scenarios that share the criterion's condition variables. Outcomes nothing can
vouch for are left out and tagged `needs-expert:<key>` for the expert to confirm.

## Regression safety

Scenario sets are edited: branches get synthesized, cases get retired, an incident becomes a test.
`playbook bank` keeps every scenario a procedure has been run on, with its tags and how each
version scored it, in `runs/<procedure>/bank.json`. It folds in `scenarios.yaml` and every stored
report on each call, and `--add FILE` merges another set, for example the synthesized one.

```
support-triage bank: 16 scenario(s), 11 tag(s), versions v1, v2, v3, 14 with a recorded failure
  enterprise        6 scenario(s), 6 with a recorded failure
  pii-phone         2 scenario(s), 2 with a recorded failure
  sev3              4 scenario(s), 2 with a recorded failure
historical failures: triage-01, triage-02, triage-03, triage-04, triage-05, triage-06, triage-07, triage-08, triage-09, triage-12, triage-13, triage-14, triage-15, triage-16
```

`playbook regress` replays the bank against a version and compares each scenario with the last
version that scored it. A scenario that used to pass and now fails is a regression and fails the
run; a scenario the bank has never scored is new, so its failure is reported separately and does
not trip the guard. `--tag` narrows the replay, `--failures` replays only the cases with a recorded
failure. Pass rates are reported per tag, which is where a version that trades one segment for
another shows up (4 of the 11 tag rows shown):

```
support-triage regression of v3: 16 replayed, pass rate 100.0%, 2 fixed, 0 broken, 0 new failing
  fixed: triage-05, triage-12
per tag:
  enterprise        6/6  100.0%
  pii-phone         2/2  100.0%
  sev3              4/4  100.0%
  sev4              3/3  100.0%
guard passed
```

Against a v4 carrying a deliberately bad correction (`When severity is sev3, transition to
"Done".`), the guard exits non-zero and names what broke:

```
support-triage regression of v4: 16 replayed, pass rate 87.5%, 0 fixed, 2 broken, 0 new failing
  broken: triage-10, triage-12
per tag:
  kb-miss           5/7  71.4%
  pii-phone         1/2  50.0%
  sev3              2/4  50.0%
GUARD FAILED: 2 scenario(s) regressed
```

## AWS deployment

```
make stack-up                       # LocalStack (set LOCALSTACK_PORT if 4566 is taken)
make tf-apply-local                 # apply deploy/terraform against LocalStack
make lambda-zip                     # build build/lambda with dependencies and procedures
terraform -chdir=deploy/terraform apply -var lambda_source_dir=$PWD/build/lambda   # real AWS
```

The stack creates `playbook-<env>-artifacts` (S3, versioned, encrypted, private),
`playbook-<env>-runs` and its dead-letter queue (SQS), `playbook-<env>-run-index` (DynamoDB,
`pk`/`sk`), the `playbook-<env>/api-keys` secret (values set out of band) and the
`playbook-<env>-runner` Lambda consuming the queue one message at a time. A message is
`{"procedure": "support_triage", "scenario_id": "triage-01", "prompt_version": 3}`; the handler
loads the secret into the environment, runs the scenario live, grades it and writes the trace to
S3 with an index item. `terraform fmt`, `validate` and `apply` against LocalStack are part of the
local checks. `deploy/docker-compose.yml` runs LocalStack and the fakes; the `Dockerfile` is a
multi-stage build that runs as a non-root user.

## Layout

```
playbook/ingest      SOP and walkthrough parser, Procedure model
playbook/agent       PromptSpec, tools, tool loop, run store
playbook/evals       scenarios, rubric, grader, judge, reports, scenario bank, regression run
playbook/feedback    correction derivation, improvement loop, review queue, diff, promotion
playbook/cli.py      the playbook command
fakes/               offline Messages API, Jira and Slack stand-ins
procedures/          two sample procedures with rubrics and scenario sets
deploy/terraform     AWS stack; deploy/lambda the runner handler; deploy/docker-compose.yml
tests/               pytest suite (offline; LocalStack and live tests skip unless configured)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for schemas and the offline grammar, and
[CONTRIBUTING.md](CONTRIBUTING.md) for adding procedures and criteria.

## Releases

| version | date | what shipped |
|---|---|---|
| [v4.0.0](https://github.com/SAY-5/playbook/releases/tag/v4.0.0) | 2026-09-10 | tagged scenario bank, regression replay, previously-passing guard |
| [v3.0.0](https://github.com/SAY-5/playbook/releases/tag/v3.0.0) | 2026-09-10 | review queue, version diff, promotion gate, audit trail |
| [v2.0.0](https://github.com/SAY-5/playbook/releases/tag/v2.0.0) | 2026-09-08 | decision-branch coverage and scenario synthesis |
| [v1.0.0](https://github.com/SAY-5/playbook/releases/tag/v1.0.0) | 2026-09-08 | ingest, prompt versions, tool loop, rubric evals, feedback loop, Terraform stack |

Full entries in [CHANGELOG.md](CHANGELOG.md).
