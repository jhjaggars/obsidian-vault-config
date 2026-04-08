#!/bin/bash
# Daily Calendar Sync - Complete Workflow
# Syncs calendar events to today's daily note with transcripts

# Don't use set -e - let script continue on individual errors
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
PKM_SYNC="${PKM_SYNC:-$(command -v pkm-sync 2>/dev/null || echo "pkm-sync")}"
SYNC_SCRIPT="$VAULT_DIR/.claude/skills/calendar-sync-lib/sync_calendar.py"

# Colors for output - disable if not a terminal (background execution)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    NC='\033[0m' # No Color
else
    GREEN=''
    YELLOW=''
    RED=''
    NC=''
fi

# Get today's date components
TODAY=$(date +%Y-%m-%d)
YEAR=$(date +%Y)
MONTH_NUM=$(date +%m)
MONTH_NAME=$(date +%B)
DAY_NAME=$(date +%A)

# Construct daily note path — try CLI first, fall back to manual construction
OBSIDIAN_CLI=""
if command -v obsidian &>/dev/null; then
    OBSIDIAN_CLI="obsidian"
elif [ -x "/Applications/Obsidian.app/Contents/MacOS/obsidian" ]; then
    OBSIDIAN_CLI="/Applications/Obsidian.app/Contents/MacOS/obsidian"
fi

DAILY_NOTE=""
if [ -n "$OBSIDIAN_CLI" ]; then
    DAILY_NOTE_REL=$(timeout 10 "$OBSIDIAN_CLI" daily:path 2>/dev/null)
    if [ -n "$DAILY_NOTE_REL" ]; then
        DAILY_NOTE="$VAULT_DIR/$DAILY_NOTE_REL"
    fi
fi

if [ -z "$DAILY_NOTE" ]; then
    DAILY_NOTE="$VAULT_DIR/daily/$YEAR/$MONTH_NUM-$MONTH_NAME/$TODAY-$DAY_NAME.md"
fi

echo -e "${GREEN}=== Daily Calendar Sync ===${NC}"
echo "Date: $TODAY ($DAY_NAME)"
echo "Daily note: $DAILY_NOTE"
echo ""

# Check if daily note exists - exit gracefully if not (weekends, before note created)
if [ ! -f "$DAILY_NOTE" ]; then
    echo -e "${YELLOW}Daily note not found at $DAILY_NOTE${NC}"
    echo "Skipping sync (note not created yet or weekend)"
    exit 0
fi

# Step 1: Fetch calendar events
echo -e "${YELLOW}Fetching calendar events...${NC}"
CALENDAR_JSON=$("$PKM_SYNC" calendar --start today --end today --include-details --format json 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$CALENDAR_JSON" ]; then
    echo -e "${RED}Error: Failed to fetch calendar events${NC}"
    echo "Make sure pkm-sync is authenticated (run: pkm-sync setup)"
    # Don't exit 1 in background mode - just skip
    exit 0
fi

EVENT_COUNT=$(echo "$CALENDAR_JSON" | jq '. | length')
echo -e "${GREEN}Found $EVENT_COUNT events${NC}"

# Step 2: Generate meeting table and get transcript list
echo -e "${YELLOW}Generating meeting table...${NC}"
TABLE_OUTPUT=$(echo "$CALENDAR_JSON" | python3 "$SYNC_SCRIPT" 2>&1)

# Split stdout (table) from stderr (transcript list)
MEETING_TABLE=$(echo "$TABLE_OUTPUT" | sed -n '/^| Time/,/^$/p')
TRANSCRIPT_INFO=$(echo "$TABLE_OUTPUT" | sed -n '/---TRANSCRIPTS---/,$ p' | grep -v "^---TRANSCRIPTS---" || true)

# Step 3: Download transcripts
TRANSCRIPT_COUNT=0
if [ -n "$TRANSCRIPT_INFO" ]; then
    echo -e "${YELLOW}Downloading Gemini transcripts...${NC}"

    # Parse JSON list of transcripts
    while IFS= read -r transcript; do
        URL=$(echo "$transcript" | jq -r '.url' 2>/dev/null || echo "")
        TITLE=$(echo "$transcript" | jq -r '.sanitized_title' 2>/dev/null || echo "")
        DATE=$(echo "$transcript" | jq -r '.date' 2>/dev/null || echo "")

        if [ -n "$URL" ] && [ -n "$TITLE" ] && [ "$URL" != "null" ]; then
            # Build hierarchical path: Meetings/YYYY/MM-Month/DD-Day/YYYY-MM-DD-Title.md
            TRANS_DAY_NAME=$(date -j -f "%Y-%m-%d" "$DATE" +%A)
            TRANS_MONTH_NUM=$(echo "$DATE" | cut -d'-' -f2)
            TRANS_MONTH_NAME=$(date -j -f "%Y-%m-%d" "$DATE" +%B)
            TRANS_DAY_NUM=$(echo "$DATE" | cut -d'-' -f3)
            TRANS_YEAR=$(echo "$DATE" | cut -d'-' -f1)
            TRANS_DIR="$VAULT_DIR/Meetings/$TRANS_YEAR/$TRANS_MONTH_NUM-$TRANS_MONTH_NAME/$TRANS_DAY_NUM-$TRANS_DAY_NAME"
            mkdir -p "$TRANS_DIR"
            TRANSCRIPT_FILE="$TRANS_DIR/$DATE-$TITLE.md"
            echo "  - $TITLE"

            if "$PKM_SYNC" drive fetch "$URL" --format md > "$TRANSCRIPT_FILE" 2>/dev/null; then
                TRANSCRIPT_COUNT=$((TRANSCRIPT_COUNT + 1))
            else
                echo -e "    ${RED}Warning: Failed to download transcript${NC}"
            fi
        fi
    done < <(echo "$TRANSCRIPT_INFO" | jq -c '.[]' 2>/dev/null || echo "")

    echo -e "${GREEN}Downloaded $TRANSCRIPT_COUNT transcripts${NC}"
else
    echo "No transcripts available"
fi

# Step 4: Update daily note
echo -e "${YELLOW}Updating daily note...${NC}"

# Create a temporary file with the new content
TEMP_FILE=$(mktemp)

# Extract everything before ### Meetings (excluding the ### Meetings line itself)
sed -n '1,/^### Meetings/p' "$DAILY_NOTE" | sed '$d' > "$TEMP_FILE"

# Add the new meeting table
echo "### Meetings" >> "$TEMP_FILE"
echo "$MEETING_TABLE" >> "$TEMP_FILE"
echo "" >> "$TEMP_FILE"

# Preserve all sections that come after ### Meetings in the original note.
# Use awk to find the first ### heading after ### Meetings and append everything from there.
# This correctly handles any sections: ### Digest, ### Action Items, ### Todo, ### Notes created today, etc.
if grep -q "^\*\*Notes:\*\*" "$DAILY_NOTE"; then
    # Legacy **Notes:** format
    sed -n '/^\*\*Notes:\*\*/,$ p' "$DAILY_NOTE" >> "$TEMP_FILE"
else
    awk '/^### Meetings/{found=1; next} found && /^### /{found=2} found==2{print}' "$DAILY_NOTE" >> "$TEMP_FILE"
fi

# Replace the daily note with the updated version
mv "$TEMP_FILE" "$DAILY_NOTE"

echo -e "${GREEN}✓ Daily note updated${NC}"
echo ""
echo "Summary:"
echo "  - Events synced: $EVENT_COUNT"
echo "  - Transcripts downloaded: $TRANSCRIPT_COUNT"
echo "  - Daily note: $DAILY_NOTE"
