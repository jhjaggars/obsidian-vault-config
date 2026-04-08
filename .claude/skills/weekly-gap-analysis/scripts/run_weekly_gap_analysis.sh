#!/bin/bash
# Weekly gap analysis: compare status report emails vs Work Pipeline kanban
# Runs every Friday via launchd (com.user.weekly-gap-analysis)
# Produces: Projects/Work/Status Report Gap Analysis.md

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

AGENT_RUNNER="$VAULT_DIR/.claude/skills/daily-sync-all/scripts/run_agent.py"
LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/weekly-gap-analysis}"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== Weekly Gap Analysis: Started ==="

# Re-index the last week of emails to ensure fresh data
log "Step 1/2: Re-indexing last 7 days of pkm-sync data"
if command -v pkm-sync &>/dev/null; then
    pkm-sync index --since 7d \
        || log "WARNING: pkm-sync index had errors (non-fatal)"
else
    log "WARNING: pkm-sync not found in PATH, skipping re-index"
fi

# Run the gap-analyzer agent
log "Step 2/2: Running gap-analyzer agent"
if [ -f "$AGENT_RUNNER" ]; then
    (cd "$VAULT_DIR" && "$UV" run "$AGENT_RUNNER" \
        gap-analyzer \
        "Run weekly status report gap analysis for today's date." \
        2>&1) \
        || log "WARNING: gap-analyzer agent had errors (non-fatal)"
else
    log "ERROR: Agent runner not found at $AGENT_RUNNER"
    exit 1
fi

log "=== Weekly Gap Analysis: Finished ==="
