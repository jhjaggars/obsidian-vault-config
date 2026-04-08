#!/bin/bash
# Phase 1 orchestrator: sync all data sources
# Called by launchd agent (hourly) and /daily-sync-all skill (on demand)
#
# Steps:
#   1. ensure_daily_note.sh   - create today's note if missing
#   2. pkm-sync sync --since 1d - Gmail, Drive, Slack, Calendar
#   3. sync_daily_calendar.sh  - update Meetings table in daily note
#   4. sync_daily_work.py      - JIRA + PR notes
#   5. pkm-sync index --since 1d - update vector embeddings
#   6. project-tracker agent   - Meeting Prep + Active Projects + Deadlines
#
# Flags:
#   --skip-index   Skip step 5 (vector indexing) — useful for testing step 6

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

SKILL_DIR="$VAULT_DIR/.claude/skills/daily-sync-all"
CALENDAR_SYNC="$VAULT_DIR/.claude/skills/daily-calendar-sync/sync_daily_calendar.sh"
WORK_SYNC="$VAULT_DIR/.claude/skills/daily-work-sync/scripts/sync_daily_work.py"
LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/daily-work-sync}"

SKIP_INDEX=false
for arg in "$@"; do
    [ "$arg" = "--skip-index" ] && SKIP_INDEX=true
done

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

step() {
    echo ""
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ─── $* ───"
}

log "=== Daily Sync All: Started ==="

# Step 1: Ensure daily note exists
step "Step 1/6: Ensuring today's daily note exists"
bash "$SKILL_DIR/scripts/ensure_daily_note.sh" \
    || log "WARNING: ensure_daily_note had errors (non-fatal)"

# Step 2: pkm-sync sync (Gmail archive, Drive, Slack, Calendar, Jira)
step "Step 2/6: pkm-sync sync --since 1d"
if command -v pkm-sync &>/dev/null; then
    pkm-sync sync --since 1d \
        || log "WARNING: pkm-sync sync had errors (non-fatal)"
else
    log "WARNING: pkm-sync not found in PATH, skipping"
fi

# Step 2b: Normalize attendees in pkm-sync meeting notes (pass 1)
step "Step 2b/6: Normalize attendee identifiers in meeting notes (pass 1)"
NORMALIZE_ATTENDEES="$VAULT_DIR/.claude/skills/calendar-sync-lib/normalize_attendees.py"
if [ -f "$NORMALIZE_ATTENDEES" ]; then
    python3 "$NORMALIZE_ATTENDEES" "$VAULT_DIR/Meetings/" \
        || log "WARNING: normalize_attendees had errors (non-fatal)"
else
    log "WARNING: $NORMALIZE_ATTENDEES not found, skipping"
fi

# Step 2c: Auto-create People pages for unresolved attendees using FastRover
step "Step 2c/6: Auto-create People pages for unresolved attendees"
CREATE_PEOPLE="$VAULT_DIR/.claude/skills/calendar-sync-lib/create_people_pages.py"
if [ -f "$CREATE_PEOPLE" ]; then
    python3 "$CREATE_PEOPLE" "$VAULT_DIR/Meetings/" \
        || log "WARNING: create_people_pages had errors (non-fatal)"
else
    log "WARNING: $CREATE_PEOPLE not found, skipping"
fi

# Step 2d: Re-run normalize_attendees to resolve newly-created People pages
step "Step 2d/6: Normalize attendee identifiers in meeting notes (pass 2)"
if [ -f "$NORMALIZE_ATTENDEES" ]; then
    python3 "$NORMALIZE_ATTENDEES" "$VAULT_DIR/Meetings/" \
        || log "WARNING: normalize_attendees (pass 2) had errors (non-fatal)"
fi

# Step 3: Calendar sync → Meetings table in daily note
step "Step 3/6: Calendar sync"
if [ -f "$CALENDAR_SYNC" ]; then
    bash "$CALENDAR_SYNC" \
        || log "WARNING: calendar sync had errors (non-fatal)"
else
    log "WARNING: $CALENDAR_SYNC not found, skipping"
fi

# Step 4: Work sync (JIRA + GitHub PRs)
step "Step 4/6: Work sync (JIRA + PRs)"
if [ -f "$WORK_SYNC" ]; then
    "$UV" run "$WORK_SYNC" "$VAULT_DIR" \
        || log "WARNING: work sync had errors (non-fatal)"
else
    log "WARNING: $WORK_SYNC not found, skipping"
fi

# Step 4.5: Project sync (Related Items sections)
step "Step 4.5/6: Project sync"
PROJECT_SYNC="$VAULT_DIR/.claude/skills/project-sync/scripts/project_sync.py"
if [ -f "$PROJECT_SYNC" ]; then
    "$UV" run "$PROJECT_SYNC" "$VAULT_DIR" \
        || log "WARNING: project sync had errors (non-fatal)"
fi

# Step 5: Update vector index
if [ "$SKIP_INDEX" = true ]; then
    step "Step 5/6: Skipping vector index (--skip-index)"
else
    step "Step 5/6: pkm-sync index --since 1d"
    if command -v pkm-sync &>/dev/null; then
        pkm-sync index --since 1d \
            || log "WARNING: pkm-sync index had errors (non-fatal)"
    else
        log "WARNING: pkm-sync not found in PATH, skipping index"
    fi
fi

# Step 6: Run project-tracker agent (Meeting Prep + Active Projects + Deadlines)
step "Step 6/7: project-tracker agent"
AGENT_RUNNER="$SKILL_DIR/scripts/run_agent.py"
if [ -f "$AGENT_RUNNER" ]; then
    (cd "$VAULT_DIR" && "$UV" run "$AGENT_RUNNER" \
        project-tracker \
        "Run the project tracker agent for today's daily note." \
        2>&1) \
        || log "WARNING: project-tracker agent had errors (non-fatal)"
else
    log "WARNING: $AGENT_RUNNER not found, skipping project-tracker"
fi

# Step 7: Run daily-curator agent (Digest + Action Items)
step "Step 7/8: daily-curator agent"
if [ -f "$AGENT_RUNNER" ]; then
    (cd "$VAULT_DIR" && "$UV" run "$AGENT_RUNNER" \
        daily-curator \
        "Curate today's daily note: write the Digest and Action Items sections." \
        2>&1) \
        || log "WARNING: daily-curator agent had errors (non-fatal)"
else
    log "WARNING: $AGENT_RUNNER not found, skipping daily-curator"
fi

# Step 8: Extract and summarize today's conversations (Slack DMs + email)
step "Step 8/8: Conversation sync"
CONV_EXTRACT="$SKILL_DIR/scripts/extract_conversations.py"
if [ -f "$CONV_EXTRACT" ]; then
    CONV_JSON=$("$UV" run "$CONV_EXTRACT" "$VAULT_DIR" 2>&1 | tail -1) \
        || log "WARNING: conversation extraction had errors (non-fatal)"
    if [ -n "$CONV_JSON" ] && [ -f "$CONV_JSON" ]; then
        (cd "$VAULT_DIR" && "$UV" run "$AGENT_RUNNER" \
            conversation-summarizer \
            "Summarize conversations from $CONV_JSON into today's daily note." \
            2>&1) \
            || log "WARNING: conversation-summarizer agent had errors (non-fatal)"
    else
        log "WARNING: conversation extraction produced no output file, skipping summarizer"
    fi
else
    log "WARNING: $CONV_EXTRACT not found, skipping conversation sync"
fi

log ""
log "=== Daily Sync All: Finished ==="
