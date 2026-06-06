#!/usr/bin/env bash
# Smoke test for process-topic Superset dispatch (QUA-187).
#
# Proves the dispatch *mechanism* end-to-end against a LIVE Superset host:
#   A) `superset agents create` can create a file.
#   B) prompt-file dispatch can UPDATE an existing file, write a completion
#      sentinel, and that the update is detectable by sentinel + mtime change
#      (not by mere file existence).
#
# This is a maintainer/integration smoke, NOT a CI unit test: it needs a
# running Superset host, a valid $SUPERSET_WORKSPACE_ID, and an agent preset
# whose model backend actually executes agentic tasks. The current CLI has no
# `agents run` and no transcript/status/logs command, so completion is judged
# purely from disk artifacts — exactly as the skill does.
#
# Usage:
#   SUPERSET_WORKSPACE_ID=<id> ./smoke-dispatch.sh [--agent <preset>] [--timeout <sec>]
#
# --agent defaults to `claude` (a real-backend preset) so the smoke can pass
# on its own. The production skill dispatches with ${QUASI_SUPERSET_AGENT:-copilot};
# if your configured agent's backend stalls, this smoke will time out — that is
# the same failure mode the skill detects via poll timeout.
set -euo pipefail

AGENT="claude"
TIMEOUT=240
while [ $# -gt 0 ]; do
  case "$1" in
    --agent) AGENT="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

: "${SUPERSET_WORKSPACE_ID:?set SUPERSET_WORKSPACE_ID to a live workspace id}"
command -v superset >/dev/null || { echo "superset CLI not found" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/quasi-smoke-XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
RUNS="$WORK/runs"; mkdir -p "$RUNS"

A_FILE="$WORK/smoke-A.txt"
B_TARGET="$WORK/smoke-B-existing.md"
B_PROMPT="$WORK/smoke-B.prompt.md"
B_SENTINEL="$RUNS/smoke-B.json"

# Fixture B: an EXISTING file that must be overwritten (existence stays true).
printf 'BEFORE: this line must be replaced\n' > "$B_TARGET"
B_BASELINE_MTIME="$(stat -f %m "$B_TARGET" 2>/dev/null || stat -c %Y "$B_TARGET")"

cat > "$B_PROMPT" <<EOF
# Smoke task (prompt-file dispatch)
Perform every step. Do NOT skip a step because a file already exists.
1. Overwrite "$B_TARGET" so its entire contents become exactly this line:
   AFTER: prompt-file dispatch updated this existing file
2. Then write a completion sentinel JSON to "$B_SENTINEL" with exactly:
   {"status":"done","updated":["$B_TARGET"]}
3. Stop.
EOF

echo "== dispatch A (create a file) =="
superset agents create --workspace "$SUPERSET_WORKSPACE_ID" --agent "$AGENT" \
  --prompt "Write a file at $A_FILE containing exactly the word OK. Then stop." \
  --json >/dev/null

echo "== dispatch B (prompt-file updates an existing file + sentinel) =="
superset agents create --workspace "$SUPERSET_WORKSPACE_ID" --agent "$AGENT" \
  --prompt "Read $B_PROMPT and perform it exactly. Do not skip any step because a target file already exists." \
  --json >/dev/null

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }

deadline=$((SECONDS + TIMEOUT))
a_ok=0; b_ok=0
while [ $SECONDS -lt $deadline ]; do
  [ -f "$A_FILE" ] && [ "$(cat "$A_FILE")" = "OK" ] && a_ok=1
  # B done = sentinel exists AND target mtime advanced (sentinel alone is not trusted).
  if [ -f "$B_SENTINEL" ] && [ "$(mtime "$B_TARGET")" -gt "$B_BASELINE_MTIME" ]; then b_ok=1; fi
  [ "$a_ok" = 1 ] && [ "$b_ok" = 1 ] && break
  sleep 5
done

echo
echo "A (create file):           $([ "$a_ok" = 1 ] && echo PASS || echo FAIL)"
echo "B (update existing+sentinel): $([ "$b_ok" = 1 ] && echo PASS || echo FAIL)"
[ "$a_ok" = 1 ] && [ "$b_ok" = 1 ] || { echo "SMOKE FAILED (timeout ${TIMEOUT}s)"; exit 1; }
echo "SMOKE PASSED"
