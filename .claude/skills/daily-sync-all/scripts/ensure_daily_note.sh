#!/bin/bash
# Ensure today's daily note exists.
# Creates daily/YYYY/MM-Month/YYYY-MM-DD-DayName.md from scratch if missing.
# Safe to run multiple times (idempotent).

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

# Date components
TODAY=$(date +%Y-%m-%d)
YEAR=$(date +%Y)
MONTH_NUM=$(date +%m)
MONTH_NAME=$(date +%B)
DAY_NAME=$(date +%A)

# Human-readable heading date (matches Templater: "Friday, February 27, 2026")
MONTH_DAY=$(date +%B\ %d,\ %Y)
HEADING="$DAY_NAME, $MONTH_DAY"

# Path — try CLI first, fall back to manual construction
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

DAILY_DIR=$(dirname "$DAILY_NOTE")

if [ -f "$DAILY_NOTE" ]; then
    echo "Daily note already exists: $DAILY_NOTE"
    exit 0
fi

mkdir -p "$DAILY_DIR"

cat > "$DAILY_NOTE" <<EOF
# $HEADING
### Meetings
-
### Digest

### Action Items

### Todo
-
### Notes created today
\`\`\`dataview
LIST FROM "" WHERE file.cday = date("$TODAY") SORT file.ctime asc
\`\`\`
### Notes modified today
\`\`\`dataview
LIST FROM "" WHERE file.mday = date("$TODAY") SORT file.mtime asc
\`\`\`
EOF

echo "Created daily note: $DAILY_NOTE"
