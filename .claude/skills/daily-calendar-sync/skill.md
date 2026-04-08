# Daily Calendar Sync Skill

Sync calendar events to today's daily note with meeting information and Gemini transcripts.

## When to Use

Use this skill when the user wants to:
- Sync today's calendar to their daily note
- Update the meeting table in their daily note
- Fetch Gemini transcripts for meetings
- Refresh meeting information throughout the day

Trigger phrases:
- "sync my calendar"
- "update today's meetings"
- "fetch meeting transcripts"
- "sync daily note"
- "update meeting table"

## What This Skill Does

This skill automates the complete workflow of syncing calendar events to the user's Obsidian daily note:

1. **Fetches calendar events** for today using `pkm-sync calendar`
2. **Generates a meeting table** with:
   - Meeting start times (12-hour format)
   - Wiki-links to meeting notes (in the standard Meetings/ hierarchy)
   - Attendee lists (filtered and formatted)
   - Links to Gemini transcripts (when available)
3. **Downloads Gemini transcripts** from Google Drive and saves them to the Meetings/ hierarchy
4. **Updates the daily note** with the meeting table under the `### Meetings` section

## Key Features

- **Idempotent**: Safe to run multiple times throughout the day
- **Smart filtering**: Removes the user from attendee lists, filters out calendar resources
- **Transcript detection**: Automatically identifies "Notes by Gemini" attachments
- **Incremental updates**: Downloads only new transcripts
- **Preserves notes**: Keeps existing meeting notes in the daily note

## File Locations

- **Daily notes**: `daily/YYYY/MM-Month/YYYY-MM-DD-Day.md`
- **Meeting notes**: `Meetings/YYYY/MM-Month/DD-Day/YYYY-MM-DD-Title.md`
- **Transcripts**: Stored in same location as meeting notes in Meetings/ hierarchy
- **Sync script**: `sync_calendar.py` (in vault root)

## Technical Details

The skill uses:
- `pkm-sync calendar` - Fetch calendar events with details and attachments
- `sync_calendar.py` - Python script that formats events as a markdown table
- `pkm-sync drive fetch` - Download Gemini transcript documents
- Direct file editing - Update the daily note's Meetings section

## Expected Behavior

When the skill runs:

1. **First run of the day**: Creates complete meeting table with all events
2. **Subsequent runs**: Updates table and fetches any new transcripts
3. **No meetings**: Creates empty table or removes table if none scheduled
4. **Failed transcript fetch**: Shows 📝 link but transcript file may be empty/error

## User Workflow

The user typically runs this:
- **Morning**: Initial sync to see the day's schedule
- **Throughout day**: Re-sync to get transcripts as meetings complete
- **End of day**: Final sync to capture all transcripts

## Implementation Steps

When invoked, execute these steps:

### Step 1: Determine today's date and daily note path

**With CLI** (preferred):
```bash
obsidian daily:path
```
This returns the exact relative path (e.g., `daily/2026/03-March/2026-03-05-Thursday.md`).

**Without CLI** (fallback):
Get the current date and construct the daily note path:
```
Today: YYYY-MM-DD (e.g., 2026-02-17)
Day name: e.g., "Tuesday"
Daily note: daily/YYYY/MM-Month/YYYY-MM-DD-Day.md
```

### Step 2: Fetch calendar events

Run pkm-sync to get today's events:
```bash
pkm-sync calendar --start today --end today --include-details --format json
```

### Step 3: Generate meeting table

Pipe the calendar JSON to the sync script:
```bash
pkm-sync calendar --start today --end today --include-details --format json | python3 $VAULT_DIR/.claude/skills/calendar-sync-lib/sync_calendar.py
```

This outputs:
- The markdown table to stdout
- List of transcripts to fetch to stderr

### Step 4: Download Gemini transcripts

For each transcript URL in the output:
```bash
pkm-sync drive fetch "<URL>" --format md > $VAULT_DIR/Meetings/YYYY/MM-Month/DD-Day/YYYY-MM-DD-Title.md
```

### Step 5: Update the daily note

Replace the `### Meetings` section in the daily note with the new table.

**Important**: Preserve any content after the meeting table (like **Notes:** section).

### Step 6: Report results

Tell the user:
- How many meetings were synced
- How many transcripts were downloaded
- Any errors encountered

## Implementation Notes

### Date Detection
The skill automatically determines "today" based on the current date. Update sync_calendar.py to use dynamic date detection rather than hardcoded "2026-02-17".

### Meeting Note Creation
Meeting note files are NOT created by this skill - only wiki-links are added. The user creates the actual meeting notes by clicking the links in Obsidian.

### Transcript Storage
Transcripts are saved as markdown files in the same date hierarchy as meeting notes:
- `Meetings/YYYY/MM-Month/DD-Day/YYYY-MM-DD-Meeting-Title.md`

### Preserving Existing Content
When updating the daily note:
1. Find the `### Meetings` heading
2. Replace content until the next `###` heading or `**Notes:**` marker
3. Keep everything after that intact

### Attendee Formatting
- Shows up to 5 attendees by name
- Displays "+X more" for larger meetings
- Filters out: the user's own email (set via `PKM_USER_EMAIL` env var), calendar resources, group calendars
- Prefers DisplayName over email username

### Error Handling
- If pkm-sync fails: Report authentication or API issues
- If transcript fetch fails: Create empty file or show error
- If daily note doesn't exist: Report that daily note needs to be created first
- If sync_calendar.py fails: Show the error and suggest checking the script

## Example Output

The skill updates the daily note to include:

```markdown
### Meetings
| Time | Meeting | Attendees | Transcript |
| ---- | ------- | --------- | ---------- |
| 8:30 AM | [[Meetings/2026/02-February/17-Tuesday/2026-02-17-Alice - Bob.md\|Alice / Bob]] | Alice Smith |  |
| 10:05 AM | [[Meetings/2026/02-February/17-Tuesday/2026-02-17-Team Standup.md\|Team Standup]] | alice, bob, carol, dave, eve (+3 more) | [[Meetings/2026/02-February/17-Tuesday/2026-02-17-Team Standup.md\|📝]] |
```

## Dependencies

- **pkm-sync**: Must be on PATH or set via `PKM_SYNC` env var
- **Python 3**: For running sync_calendar.py
- **Google OAuth**: User must have authenticated pkm-sync with Google
- **Obsidian vault**: Located at `$VAULT_DIR` (auto-detected or set via env var)
- **sync_calendar.py**: Located in vault root

## Common Issues

### "No such file or directory: daily note"
- The daily note must exist before running this skill
- Create it manually or use the daily note template first

### "Authentication failed"
- Run `pkm-sync setup` to re-authenticate with Google

### Transcripts not appearing
- Gemini transcripts only appear after meeting completes
- Re-run the skill after meetings to fetch new transcripts
- Some meetings may not have Gemini note-taking enabled

### Date mismatch in sync_calendar.py
- The script currently has hardcoded date "2026-02-17"
- This should be updated to use dynamic date detection
