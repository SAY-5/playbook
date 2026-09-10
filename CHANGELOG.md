# Changelog

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
