# Contributing

## Setup

```
make setup          # uv sync with the dev extras (Python 3.12)
make lint           # ruff check and format check
make test           # pytest; the LocalStack and live tests skip unless configured
make tf-validate    # terraform fmt and validate
make demo           # offline end-to-end run with the fakes
make demo-review    # promotion, audit, bank and regression guard on the make demo output
make lambda-zip     # Lambda bundle for x86_64 manylinux from uv.lock (any host)
make lambda-check   # import that bundle under linux/amd64 python 3.12 in Docker
```

To run the LocalStack tests (the S3 store and the Lambda handler), start LocalStack with
`make stack-up` and export `AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test`. To run the live test, export `ANTHROPIC_API_KEY`; the test sets
`PLAYBOOK_TOOLS=fake` so the live model talks to the local Jira and Slack stand-ins.

The browser demo under `web/` has its own checks: `npm run typecheck`, `npm run selfcheck` and
`npm run build`, run by the `web` job in CI.

## Adding a procedure

1. Create `procedures/<name>/` with `sop.md` (numbered steps, `{#step-id}` and `(tool: ...)`
   markers), `walkthrough.md` (transcript with `[mm:ss] Expert:` lines), optional `kb.json`.
2. Write `rubric.yaml` with the criteria the expert grades on; give a `remediation` to every
   criterion whose failure has a rule-shaped fix.
3. Write `scenarios.yaml` with intake fields and the expected outcome per scenario.
4. `uv run playbook loop procedures/<name>` and check the report reads the way the expert would.

## Adding a criterion kind

Add the name to `CRITERION_KINDS` in `playbook/evals/rubric.py` and a `_kind_<name>` method on
`Grader` returning `(passed, score, evidence, rationale)`. Evidence keys are what remediation
templates can reference.

## Releases

Additive features take a minor version; a change to the CLI or to the stored artifact layout
takes a major version. `pyproject.toml` is the only place the version is written; `__version__`
reads it from the installed package metadata.

## Conventions

- Conventional commit subjects on a single line (`feat:`, `fix:`, `test:`, `docs:`, `build:`).
- Keep the offline fakes deterministic; tests depend on it.
- Numbers quoted in the README come from `make demo` and `make demo-review` and are labelled
  offline or live.
