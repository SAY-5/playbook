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

## CLI

```
playbook ingest PROCEDURE_DIR                  parse sop.md and walkthrough.md, write procedure.json
playbook run PROCEDURE_DIR [--scenario ID]     run the agent on the scenario set, store traces
playbook eval PROCEDURE_DIR [--compare N]      run and grade a prompt version, print the report
playbook improve PROCEDURE_DIR [--dry-run]     derive corrections from the last report, create vN+1
playbook loop PROCEDURE_DIR [--max-rounds N]   run, grade, correct and re-run until plateau
playbook report PROCEDURE_DIR [--inbox]        before/after table from stored reports
playbook serve-fakes                           serve the offline model, Jira and Slack stand-ins
```

Every command accepts `--runs-dir` (or `PLAYBOOK_RUNS_DIR`); `run`, `eval` and `loop` accept
`--live`. A procedure directory contains `sop.md`, `walkthrough.md`, `rubric.yaml`,
`scenarios.yaml` and optionally `kb.json`; see `procedures/`.

Environment: `PLAYBOOK_MODEL`, `ANTHROPIC_API_KEY`, `JIRA_BASE_URL`, `JIRA_TOKEN`, `SLACK_TOKEN`,
`PLAYBOOK_RUN_STORE=local|s3`, `PLAYBOOK_S3_BUCKET`, `PLAYBOOK_DDB_TABLE`, `AWS_ENDPOINT_URL`
(LocalStack), `PLAYBOOK_MAX_STEPS`.

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
playbook/evals       scenarios, rubric, grader, judge, reports
playbook/feedback    correction derivation, improvement loop
playbook/cli.py      the playbook command
fakes/               offline Messages API, Jira and Slack stand-ins
procedures/          two sample procedures with rubrics and scenario sets
deploy/terraform     AWS stack; deploy/lambda the runner handler; deploy/docker-compose.yml
tests/               pytest suite (offline; LocalStack and live tests skip unless configured)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for schemas and the offline grammar, and
[CONTRIBUTING.md](CONTRIBUTING.md) for adding procedures and criteria.
