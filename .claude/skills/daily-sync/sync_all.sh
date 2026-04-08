#!/bin/bash
# Combined sync: calendar + work (JIRA/GitHub PRs)
# Called by launchd agent com.user.daily-work-sync every hour

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

CALENDAR_SYNC="$VAULT_DIR/.claude/skills/daily-calendar-sync/sync_daily_calendar.sh"
WORK_SYNC="$VAULT_DIR/.claude/skills/daily-work-sync/scripts/sync_daily_work.py"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Hourly Sync Started ==="

# Run calendar sync
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running calendar sync..."
bash "$CALENDAR_SYNC" || echo "[$(date '+%Y-%m-%d %H:%M:%S')] Calendar sync had errors (non-fatal)"

# Run work sync
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running work sync..."
"$UV" run "$WORK_SYNC" "$VAULT_DIR" || echo "[$(date '+%Y-%m-%d %H:%M:%S')] Work sync had errors (non-fatal)"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Hourly Sync Finished ==="
