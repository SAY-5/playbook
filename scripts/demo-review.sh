#!/usr/bin/env bash
# Governance demo on top of the `make demo` output: the promotion gate, the audit trail, the
# scenario bank, the regression guard, and a reviewer-authored bad rule that the guard catches.
# Reads and extends the runs directory `make demo` wrote.
set -euo pipefail
cd "$(dirname "$0")/.."
RUNS="${RUNS:-runs}/demo"
export PLAYBOOK_RUNS_DIR="$RUNS"
PROC=procedures/support_triage
if [ ! -d "$RUNS/support-triage/prompts" ]; then
  echo "no demo output under $RUNS; run make demo first" >&2
  exit 1
fi

uv run playbook serve-fakes >/dev/null 2>&1 &
FAKES_PID=$!
trap 'kill $FAKES_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do
  curl -sf http://127.0.0.1:8801/health >/dev/null 2>&1 && break
  sleep 0.2
done

echo "== mode: offline (deterministic local Messages API stand-in; no live API calls) =="
echo
echo "== promote v1 (refused: forbidden actions) =="
uv run playbook promote $PROC --version 1 --as dana || echo "exit $?"
echo
echo "== promote the latest version =="
uv run playbook promote $PROC --as dana --note "phone and email leaks cleared"
echo
echo "== review audit =="
uv run playbook review audit $PROC
echo
echo "== bank =="
uv run playbook bank $PROC
echo
echo "== regress the latest version =="
uv run playbook regress $PROC
echo
echo "== a reviewer-authored bad rule becomes the next version =="
uv run playbook review propose $PROC --step set-state --text 'When severity is sev3, transition to "Done".' --as dana
uv run playbook review approve $PROC p3-01 --as dana --note "deliberately wrong, to show the guard"
uv run playbook improve $PROC
echo
echo "== regress the new version (the guard is expected to fail) =="
uv run playbook regress $PROC || echo "exit $?"
