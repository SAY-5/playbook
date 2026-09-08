#!/usr/bin/env bash
# Offline demo: serve the fakes, ingest both procedures, run the feedback loop from prompt v1
# until the pass rate plateaus, then print the before/after tables and the Jira/Slack evidence.
set -euo pipefail
cd "$(dirname "$0")/.."
RUNS="${RUNS:-runs}/demo"
export PLAYBOOK_RUNS_DIR="$RUNS"
rm -rf "$RUNS"

uv run playbook serve-fakes >/dev/null 2>&1 &
FAKES_PID=$!
trap 'kill $FAKES_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do
  curl -sf http://127.0.0.1:8801/health >/dev/null 2>&1 && break
  sleep 0.2
done

echo "== mode: offline (deterministic local Messages API stand-in; no live API calls) =="
for proc in procedures/support_triage procedures/incident_comms; do
  echo
  echo "== ingest $proc =="
  uv run playbook ingest "$proc" | head -8
  echo
  echo "== feedback loop $proc =="
  uv run playbook loop "$proc" --max-rounds 5
done

echo
echo "== evidence: fake Jira and Slack inboxes after the last version =="
uv run playbook report procedures/incident_comms --inbox | awk '/Jira inbox/{show=1} show'
