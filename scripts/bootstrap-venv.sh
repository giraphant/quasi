#!/usr/bin/env bash
# bootstrap-venv.sh — ensure quasi's shared Python venv is present and in sync
# with scripts/requirements.txt.
#
# Resolves the persistent data dir in this order:
#   1. $CLAUDE_PLUGIN_DATA     (set by Claude Code plugin loader)
#   2. $HOME/.cache/quasi      (stable fallback for bare/dev invocation)
#
# It will NOT write under $CLAUDE_PLUGIN_ROOT, since that directory is
# ephemeral and gets cleaned up after plugin updates.
#
# Idempotent. Exits 0 when already in sync. Designed to be run from a
# SessionStart hook, but safe to invoke manually:
#     "${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap-venv.sh"

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(dirname "$SCRIPT_DIR")"
REQ_SRC="$SCRIPT_DIR/requirements.txt"

DATA_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.cache/quasi}"
VENV="$DATA_DIR/.venv"
REQ_DST="$DATA_DIR/requirements.txt"

mkdir -p "$DATA_DIR"

if [ ! -x "$VENV/bin/python" ]; then
    echo "[quasi] creating venv at $VENV ..." >&2
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    rm -f "$REQ_DST"  # force install below
fi

if ! diff -q "$REQ_SRC" "$REQ_DST" >/dev/null 2>&1; then
    echo "[quasi] syncing python deps from $REQ_SRC ..." >&2
    if "$VENV/bin/pip" install --quiet --upgrade -r "$REQ_SRC"; then
        cp "$REQ_SRC" "$REQ_DST"
    else
        echo "[quasi] pip install failed; will retry on next session" >&2
        rm -f "$REQ_DST"
        exit 1
    fi
fi
