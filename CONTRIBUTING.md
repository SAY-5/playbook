# Contributing

## Setup

```
make setup          # uv sync with the dev extras (Python 3.12)
make lint           # ruff check and format check
make test           # pytest; the LocalStack and live tests skip unless configured
make tf-validate    # terraform fmt and validate
make demo           # offline end-to-end run with the fakes
```

To run the S3 store test, start LocalStack with `make stack-up` and export
`AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test`.
To run the live test, export `ANTHROPIC_API_KEY`.

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

## Conventions

- Conventional commit subjects on a single line (`feat:`, `fix:`, `test:`, `docs:`, `build:`).
- Keep the offline fakes deterministic; tests depend on it.
- Numbers quoted in the README come from `make demo` and are labelled offline or live.
