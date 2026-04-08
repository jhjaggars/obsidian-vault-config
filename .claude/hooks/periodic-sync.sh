#!/bin/bash
# Throttled periodic sync wrapper for Claude Code hooks
# Runs both daily-calendar-sync and daily-work-sync if 30+ minutes have elapsed

set -u  # Error on undefined variables (but don't use set -e, let script continue on errors)

# Paths relative to project directory
VAULT_DIR="${CLAUDE_PROJECT_DIR}"
TIMESTAMP_FILE="${VAULT_DIR}/.claude/.last-periodic-sync"
LOG_FILE="${VAULT_DIR}/.claude/logs/periodic-sync.log"
CALENDAR_SYNC="${VAULT_DIR}/.claude/skills/daily-calendar-sync/sync_daily_calendar.sh"
WORK_SYNC="${VAULT_DIR}/.claude/skills/daily-work-sync/scripts/sync_daily_work.py"

# Throttle interval in seconds (30 minutes)
THROTTLE_SECONDS=1800

# Disable ANSI colors in background (check if stdout is a terminal)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    GREEN=''
    YELLOW=''
    NC=''
fi

# Log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Check throttle
NOW=$(date +%s)

if [ -f "$TIMESTAMP_FILE" ]; then
    LAST_RUN=$(cat "$TIMESTAMP_FILE")
    ELAPSED=$((NOW - LAST_RUN))

    if [ "$ELAPSED" -lt "$THROTTLE_SECONDS" ]; then
        # Too soon, skip silently
        exit 0
    fi
fi

# Update timestamp
echo "$NOW" > "$TIMESTAMP_FILE"

# Log sync start
log "${GREEN}=== Periodic Sync Started ===${NC}"

# Run calendar sync
log "${YELLOW}Running calendar sync...${NC}"
if bash "$CALENDAR_SYNC" >> "$LOG_FILE" 2>&1; then
    log "${GREEN}✓ Calendar sync completed${NC}"
else
    log "${YELLOW}⚠ Calendar sync had errors (non-fatal)${NC}"
fi

# Run work sync (using uv as instructed)
log "${YELLOW}Running work sync...${NC}"
if uv run "$WORK_SYNC" "$VAULT_DIR" >> "$LOG_FILE" 2>&1; then
    log "${GREEN}✓ Work sync completed${NC}"
else
    log "${YELLOW}⚠ Work sync had errors (non-fatal)${NC}"
fi

log "${GREEN}=== Periodic Sync Finished ===${NC}"
log ""

# Always exit 0 so hook doesn't block user
exit 0
