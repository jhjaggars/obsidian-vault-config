# Daily Calendar Sync - Implementation Guide

## Quick Start

To invoke this skill, the user simply says:
- "sync my calendar"
- "update today's meetings"
- "sync daily note"

## What Claude Should Do

When this skill is invoked, execute the sync script:

```bash
$VAULT_DIR/.claude/skills/daily-calendar-sync/sync_daily_calendar.sh
```

The script will:
1. Verify the daily note exists for today
2. Fetch calendar events from Google Calendar
3. Generate a formatted meeting table
4. Download any Gemini transcripts
5. Update the daily note's Meetings section

## Expected Output

The script provides colored output showing:
- Number of events found
- Transcripts being downloaded
- Success confirmation

Example:
```
=== Daily Calendar Sync ===
Date: 2026-02-17 (Tuesday)
Daily note: $VAULT_DIR/daily/2026/02-February/2026-02-17-Tuesday.md

Fetching calendar events...
Found 8 events
Generating meeting table...
Downloading Gemini transcripts...
  - Team Biweekly Staff
  - Architecture Review
  - Platform Sync
Downloaded 3 transcripts
Updating daily note...
✓ Daily note updated

Summary:
  - Events synced: 8
  - Transcripts downloaded: 3
```

## Error Handling

If the script fails, check:

1. **Daily note doesn't exist**: Create it first or tell user to create it
2. **Authentication error**: User needs to run `pkm-sync setup`
3. **Script not found**: Verify paths in the script are correct
4. **Python error**: Check that sync_calendar.py exists in vault root

## Manual Invocation (for testing)

The user can also run the script directly from their terminal:

```bash
cd $VAULT_DIR
./.claude/skills/daily-calendar-sync/sync_daily_calendar.sh
```

## File Structure

```
ObsidianVault/
├── .claude/
│   └── skills/
│       └── daily-calendar-sync/
│           ├── skill.md                    (Skill documentation)
│           ├── sync_daily_calendar.sh      (Main sync script)
│           └── README.md                   (This file)
├── sync_calendar.py                        (Python formatter)
├── daily/
│   └── YYYY/MM-Month/YYYY-MM-DD-Day.md    (Daily notes)
└── Meetings/
    └── YYYY/MM-Month/DD-Day/...           (Meeting notes and transcripts)
```

## Customization

The script uses these configurable paths:
- `VAULT_DIR`: auto-detected (or set via env var)
- `PKM_SYNC`: auto-detected via `command -v pkm-sync` (or set via env var)
- `SYNC_SCRIPT`: `$VAULT_DIR/.claude/skills/calendar-sync-lib/sync_calendar.py`

## Idempotency

The script is safe to run multiple times per day:
- Re-fetches all events (in case meetings were added/removed)
- Re-downloads transcripts (in case new ones appeared)
- Preserves existing notes under "**Notes:**" section

## Troubleshooting

### Script fails with "command not found"
Make sure the script is executable:
```bash
chmod +x $VAULT_DIR/.claude/skills/daily-calendar-sync/sync_daily_calendar.sh
```

### No transcripts downloaded
- Transcripts only appear after meetings complete
- Not all meetings have Gemini note-taking enabled
- Run the skill again later in the day

### Table formatting looks wrong
- Check that sync_calendar.py is working correctly
- Verify the daily note has a `### Meetings` section

### Daily note gets corrupted
The script preserves content after the meeting table. If issues occur:
1. Check git history to restore previous version
2. The script looks for `**Notes:**` marker or next `###` heading
3. Report the issue so the preservation logic can be improved
