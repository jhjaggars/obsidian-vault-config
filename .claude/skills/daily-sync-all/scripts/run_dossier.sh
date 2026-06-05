#!/bin/bash
# run_dossier.sh — Standalone dossier update script.
# Runs once daily (via launchd) to update People dossiers.
# Separated from the main sync pipeline since dossier updates
# don't need to run 3x/day and are the slowest agent step.

set -u

_find_vault_root() {
    local dir
    dir="$(cd "$(dirname "$0")" && pwd)"
    while [ "$dir" != "/" ]; do
        [ -d "$dir/.obsidian" ] && echo "$dir" && return
        dir="$(dirname "$dir")"
    done
    echo "ERROR: Could not find vault root (no .obsidian/ directory found)" >&2
    exit 1
}
VAULT_DIR="${VAULT_DIR:-$(_find_vault_root)}"

_find_uv() {
    if command -v uv &>/dev/null; then command -v uv
    elif [ -x "$HOME/.local/bin/uv" ]; then echo "$HOME/.local/bin/uv"
    elif [ -x "/opt/homebrew/bin/uv" ]; then echo "/opt/homebrew/bin/uv"
    elif [ -x "/usr/local/bin/uv" ]; then echo "/usr/local/bin/uv"
    else echo "uv"; fi
}
UV="${UV:-$(_find_uv)}"

BUILD_DOSSIER="$VAULT_DIR/.claude/skills/people-dossier/scripts/build_dossier.py"
DOSSIER_DRIVER="$VAULT_DIR/.claude/skills/daily-sync-all/scripts/dossier_driver.py"

export AGENT_PIPELINE_STEP="dossier_daily"
export AGENT_TRIGGER="scheduled"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== Daily Dossier Sync: Started ==="

if [ ! -f "$BUILD_DOSSIER" ]; then
    log "ERROR: $BUILD_DOSSIER not found"
    exit 1
fi

if [ ! -f "$DOSSIER_DRIVER" ]; then
    log "ERROR: $DOSSIER_DRIVER not found"
    exit 1
fi

# Step 1: Extract dossier data
log "Extracting dossier data..."
DOSSIER_JSON=$("$UV" run "$BUILD_DOSSIER" "$VAULT_DIR" --mode daily 2>&1 | tee /dev/stderr | grep -v '^\[' | grep -v '^WARNING' | tail -1) \
    || log "WARNING: dossier extraction had errors (non-fatal)"

if [ -z "$DOSSIER_JSON" ] || [ ! -f "$DOSSIER_JSON" ]; then
    log "WARNING: dossier extraction produced no output file, exiting"
    exit 0
fi

# Step 2: Run dossier driver
log "Running dossier driver on $DOSSIER_JSON"
(cd "$VAULT_DIR" && "$UV" run "$DOSSIER_DRIVER" \
    "$DOSSIER_JSON" \
    2>&1) \
    || log "WARNING: dossier driver had errors (non-fatal)"

log "=== Daily Dossier Sync: Finished ==="
