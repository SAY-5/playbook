# Architecture

Playbook turns an expert's written SOP and recorded walkthrough into a tool-calling agent, grades
the agent's runs against the expert's rubric, and feeds the failures back into the prompt as
explicit corrections. Every prompt version, run trace and report is kept so improvements and
regressions are auditable.

```
sop.md + walkthrough.md
        |
        v
   [ingest]  Procedure (steps, tools, decision points, prohibitions, citations)
        |
        v
   [agent]   PromptSpec vN  --render-->  system prompt  --Messages API-->  tool loop
        |                                                          |  jira.* slack.* kb.search
        v                                                          v
   [evals]   Grader(rubric.yaml) <-- RunTrace (turns, tool calls, results) --> RunStore (disk | S3+DynamoDB)
        |
        v
   [feedback]  failed criteria --> corrections --> PromptSpec vN+1 --> re-run --> compare
```

## Ingest schema

`playbook.ingest.parser` reads two markdown files per procedure.

`sop.md` sections: a `# Name` heading, an optional `Purpose:` line, then `## Preconditions`,
`## Steps`, `## Escalation`, `## Never` and `## Checks`. Steps are numbered lines of the form

```
2. Create the ticket {#create-ticket} (tool: jira.create_issue)
   Free text instruction on the following indented lines.
   - Rules as indented bullets.
```

`walkthrough.md` is a transcript with `[mm:ss] Speaker: text` lines. Only `Expert:` lines are
used. Each sentence that carries a conditional (`if`, `when`, `unless`, `otherwise`, `exception`,
`always`, `must`) becomes a `DecisionPoint`; sentences with `never`, `do not` or `must not` become
prohibitions. Each decision is linked to the SOP step with the largest keyword overlap.

Everything carries a `Citation(source, line)`. The result is a `Procedure`:

| field | content |
|---|---|
| `steps` | `Step(id, index, title, instruction, tool, rules[], citation)` |
| `decision_points` | `DecisionPoint(id, text, citation, step_id, kind=decision\|forbidden)` |
| `preconditions`, `escalation_rules`, `forbidden`, `checks` | `Rule(text, citation)` lists |
| `sources` | file names used |

`playbook ingest` writes it as `runs/<procedure>/procedure.json`.

## Prompt spec

`PromptSpec(procedure_slug, version, parent_version, corrections[])` is the versioned unit. It
does not store prompt text; it renders one from the Procedure on demand, so the same procedure
text always produces the same prompt for a given version. Rendering emits the preconditions, each
step as `### Step N: title [step-id] (tool: name)` with its rules and any corrections that target
that step, the walkthrough decision points with citations, the escalation rules and the
prohibitions.

A `Correction(step_id, text, criterion, version, evidence)` is an explicit rule appended under one
step. `with_corrections()` creates version N+1 keeping all earlier corrections and dropping
duplicates. Versions are saved as `runs/<procedure>/prompts/vN.json`.

## Tool loop

`playbook.agent.loop.run_agent` drives `client.messages.create` with the six tool schemas
(`kb_search`, `jira_create_issue`, `jira_transition`, `jira_comment`, `slack_post`,
`slack_lookup_channel`). While `stop_reason == "tool_use"` it executes each block through
`ToolExecutor`, appends the assistant content and a `tool_result` user turn, and loops. The loop is
bounded by `Settings.max_steps` (default 12); exhausting it ends the run with status `max_steps`
rather than raising. Tool failures are recorded in the trace and returned to the model as
`is_error` results.

`RunTrace` holds the system prompt, intake message, every `ModelTurn` (stop reason, text, tool
uses, token usage) and every `ToolCall` (args, result, error, duration). The store writes it under
`runs/<procedure>/vN/<scenario>.json` on disk, or to the S3 bucket with a DynamoDB index item
`(pk=procedure, sk=vN#scenario)` when `PLAYBOOK_RUN_STORE=s3`.

## Offline mode

`fakes/model_server.py` implements `POST /v1/messages` with the Messages API request and response
shape, so the official `anthropic` client is used unchanged with `base_url` pointed at it. Its
behaviour is a rule engine over the system prompt: it walks the `### Step` headers in order and
calls each step's tool, but the arguments and the conditional calls are decided only by
directives it can parse:

| directive | example |
|---|---|
| project | `Use project SUP.` |
| field | `Set summary to "[{severity}] {title}".` |
| conditional field | `When severity is sev2 and tier is enterprise, set priority to "Highest".` |
| conditional post | `When tier is enterprise, post to #support-escalations mentioning the issue key.` |
| transition | `If a KB article resolves the issue, transition to "Waiting for Customer". Otherwise transition to "Triaged".` |
| exclusion | `When posting to Slack, do not include the customer email.` |

Conditions understood: `severity is sevN`, `tier is <tier>`, `impact is <level>`, `a KB match is
found` / `no KB match is found`, `the incident is customer-facing`, `report mentions "<phrase>"`,
`posting to Slack`. Prose it cannot parse is ignored, which mirrors the failure mode the feedback
loop exists to fix: the expert's meaning was clear to a person but not stated as a rule.

`fakes/jira_server.py` and `fakes/slack_server.py` implement the endpoints the tools use plus a
`GET /_inbox` for evidence and `DELETE /_inbox` for resets.

## Rubric grading

`rubric.yaml` lists criteria with a `kind`, `weight`, optional `forbidden: true` and `params`.
Kinds are deterministic checks on the trace: `tool_called`, `tool_order`, `issue_field`
(`equals`, `equals_expected` from the scenario, or a `matches` regex), `slack_post` (channel,
whether the scenario expects it, issue-key mention), `transition`, `forbidden_transition`,
`forbidden_channel`, `no_pii_in_slack`, `text_absent`. The `judge` kind produces a rationale
score: offline a transparent heuristic (completed, no tool errors, summary names the ticket), live
a model call that returns `{"score", "rationale"}`.

A run passes when it completed, no forbidden criterion failed, and the weighted score reaches
`pass_threshold`. `VersionReport` aggregates a scenario set: pass rate, mean score, per-criterion
pass rate, required-action coverage and forbidden-action count. `compare()` reports the delta and
the scenarios that newly pass or newly fail between two versions.

## Coverage and synthesis

`playbook.evals.coverage` reads each walkthrough `DecisionPoint` of kind `decision` and extracts
the variable values it names: `sevN` for `severity`, tier and impact names, and both sides of
`kb_hit` and `customer_facing` when the sentence mentions the knowledge base or customer-facing.
The product of those values gives the branches; when a variable has unmentioned values one
`otherwise` branch is added, covered by any scenario that matches none of the named branches.
Sentences that name no variable are listed as unconditional. A scenario covers a branch when its
`facts` (intake fields plus `expected.kb_hit`) take the branch's values.

Criterion coverage counts scenarios per criterion: for `when_expected` criteria the number on
each side, for `equals_expected` criteria the number per expected value, for `no_pii_in_slack`
the number of intakes carrying an email or phone number. A missing side or value is a gap.

`playbook.evals.synthesis` turns branches into scenarios. The template is the hand-written
scenario matching the most branch values (ties by id); the branch values overwrite its intake
(`kb_hit` is not an intake field, so the template must already have that value). For each
expected key the rubric references, the value comes from the branch itself or from the first
existing scenario whose facts agree on the criterion's `cond_vars`; keys without a witness are
tagged `needs-expert:<key>`. Synthesized ids are `syn-NN-<decision id>`.

## Feedback loop

Each criterion may carry a `remediation`: the target `step`, a `rule` template, `cond_vars` and an
optional `only_when_expected`. `derive_corrections` groups the failing scenarios of a criterion,
fills `<expected>` and any evidence placeholder (for example `<pii_kind>`), and replaces `<cond>`
with the smallest combination of `cond_vars` whose values on the failing scenario never coincide
with a scenario that expects a different outcome. That is how `When severity is sev1, set priority
to "Highest"` and `When severity is sev2 and tier is enterprise, set priority to "Highest"` come
out of the same rubric line.

`run_loop` runs a version, derives corrections, creates the next version, re-runs, compares, and
stops when every scenario passes, no correction applies, the pass rate stops improving, or the
round limit is hit. Every version and report stays on disk.

## Scenario bank and regression

`runs/<procedure>/bank.json` holds one entry per scenario: the scenario itself, where it came from,
and `outcomes`, a map from prompt version to pass or fail. `playbook bank` and `playbook regress`
refresh it from `scenarios.yaml` and every stored report before doing anything else, so a scenario
dropped from the set keeps its history and stays in the replay.

`run_regression` runs the selected entries on a version and, for each, looks up the highest version
below it that the bank scored. That outcome is the baseline: was passing and now failing is a
regression, was failing and now passing is a fix, and no baseline at all makes the scenario new.
The guard fails the run only for regressions. Per-tag rates come from the same outcomes, counted
once per tag a scenario carries.

## Review and promotion

`derive_corrections` produces `Correction`s; `ReviewQueue.propose` turns the ones not seen before
into `Proposal` records under `proposals/<slug>/<id>.json` in the run store, keyed `p<source
version>-<NN>`. A decision sets `status`, `reviewer`, `note`, `decided_at` and, for an edit,
`applied_text`; `final_text` is what reaches the prompt. `improve_once` applies only approved,
unapplied proposals and stamps `applied_in` on them, so a proposal enters exactly one version.
Deciding an applied proposal is refused.

`playbook.feedback.diff` renders each version as `StepView`s (the step's SOP rules followed by the
corrections attached to it) and matches them by step id: ids only in the later version are added,
ids only in the earlier one removed, and a shared id is changed when its directives, title or
position differ. Passing `after_proc` diffs across a re-ingested SOP.

`playbook.feedback.approval` gates promotion. `gate` returns one blocker per forbidden criterion
that failed in the graded report (with the scenarios) and one for undecided proposals from that
version. `PromotionLog.decide` always writes a record under `promotions/<slug>/d<version>-<NN>.json`
with the reviewer, the blockers and the pass rate, so a refusal is as auditable as a sign-off, and
`audit_trail` merges proposal decisions and promotions into one chronological list.

## Operations

`playbook.ops` reads the runs directory rather than any live state. For each procedure directory
holding at least one prompt version it takes the versions from `prompts/`, the pass rate history
and open forbidden actions from `reports/`, the promoted version and pending proposals from the
store records, and the runs from the store. Metrics come from the traces: per-tool call counts,
calls per run, tool latency as mean, p95 and max, and run wall time from `RunTrace.duration_ms`,
which the tool loop measures with a monotonic clock.

`write_run_artifact` writes one JSON file per command run under `runs/<procedure>/artifacts/`,
named `<command>-<UTC timestamp>`. It holds the version scores with their failing scenarios, the
metrics of the traces that command produced, and whatever the command adds: the loop's stop reason,
the regression run's guard verdict and per-tag rates.

## Deployment

`deploy/terraform` creates the artifact bucket (versioned, encrypted, private), the run queue with
a dead-letter queue, the DynamoDB run index, a Secrets Manager secret for the API keys, and a
Lambda runner subscribed to the queue. `deploy/lambda/handler.py` runs one scenario per SQS
message with `Settings.from_env(live=True)` after loading the secret into the environment. With
`-var-file=localstack.tfvars` the same configuration applies against LocalStack.
