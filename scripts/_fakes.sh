# Start the offline model, Jira and Slack stand-ins and wait until they answer.
#
# Sourced by the demo scripts. The wait is not decoration: the previous script's servers can still
# hold the ports for a moment, and a bind that loses that race leaves nothing listening, which used
# to show up much later as every scenario failing with a connection error. One retry covers the
# race; anything else is reported and stops the script.
start_fakes() {
  attempt=0
  while [ "$attempt" -lt 2 ]; do
    attempt=$((attempt + 1))
    uv run playbook serve-fakes >/dev/null 2>&1 &
    FAKES_PID=$!
    trap 'kill $FAKES_PID 2>/dev/null || true' EXIT
    waited=0
    while [ "$waited" -lt 75 ]; do
      if curl -sf http://127.0.0.1:8801/health >/dev/null 2>&1; then
        return 0
      fi
      kill -0 "$FAKES_PID" 2>/dev/null || break
      waited=$((waited + 1))
      sleep 0.2
    done
    kill "$FAKES_PID" 2>/dev/null || true
    wait "$FAKES_PID" 2>/dev/null || true
    sleep 1
  done
  echo "the offline fakes never answered on http://127.0.0.1:8801/health" >&2
  exit 1
}
