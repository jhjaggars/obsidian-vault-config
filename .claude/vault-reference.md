# Vault Reference

Detailed operational docs for specific vault features. Load this file on demand — it is NOT included in root context.

## Templater Configuration

- Templates folder: `Templates/`
- User scripts folder: `scripts/`
- Folder templates automatically apply to new files:
  - `Meetings/` -> `Templates/Meeting.md`
  - `People/` -> `Templates/Person.md`

### Important Scripts

**scripts/buildPageAndLink.js**: Creates a new meeting note in the hierarchical date structure (`YYYY/MM-Month/DD-Day/YYYY-MM-DD-Title.md`) and returns a wiki-link to it. Used by the "Meeting Link" template.

**dataviewscripts/pastMeetings.js**: Displays a table of previous meetings that share attendees with the current meeting note.

## Python Utilities

**`.claude/skills/daily-note-analysis/analyze_daily_notes.py`**: Analyzes daily notes to identify cleanup candidates (files with 30%+ empty sections). Run with:
```bash
python3 .claude/skills/daily-note-analysis/analyze_daily_notes.py
```

**`.claude/skills/daily-note-analysis/detailed_analysis.py`**: Provides detailed section-by-section analysis of daily notes. Run with:
```bash
python3 .claude/skills/daily-note-analysis/detailed_analysis.py
```

**`.claude/skills/calendar-sync-lib/sync_calendar.py`**: Formats calendar JSON into a markdown meeting table. Used by `daily-calendar-sync` skill.

**`.claude/skills/calendar-sync-lib/normalize_attendees.py`**: Normalizes email-based attendees to People page wiki-links in meeting frontmatter. Used by `daily-sync-all` skill.

**`.claude/skills/calendar-sync-lib/create_people_pages.py`**: Auto-creates `People/<Full Name>.md` pages for unresolved email attendees in meeting notes, populated from FastRover employee data and Slack cache. Supports `--dry-run`. Used by `daily-sync-all` skill (steps 2c/2d).

## Working with Meeting Notes

Meeting notes follow this naming pattern:
```
Meetings/YYYY/MM-MonthName/DD-DayName/YYYY-MM-DD-Title.md
```

Each meeting note includes:
- YAML frontmatter with `attendees` as an array of wiki-links
- Meeting content
- A dataview/base query at the bottom showing previous meetings with the same attendees

## Working with Daily Notes

Daily notes are created from `Templates/daily.md` and include:
- Standard sections: Meetings, Todo, Misc
- Automatic dataview queries for notes created/modified that day
- Located in `daily/YYYY/MM-MonthName/YYYY-MM-DD-DayName.md`

## `@claude` Directives in Project Notes

Project notes in `Projects/` and `Areas/` support inline `@claude` directives — natural-language instructions that the project-tracker agent picks up and executes during its daily sync run (step 6 of the pipeline).

### Syntax

Place the directive on its own line within the relevant `##` section:

```
@claude, <instruction>
```

### Examples

```markdown
## Team
[[Alice]], [[Bob]], [[Charlie]]
@claude, make this a table with each person's role

## Status
Early — POC in progress.
@claude, add a timeline table based on the JIRA epics
```

### Lifecycle

- **Pending:** `@claude, <instruction>` — will be executed on the next project-tracker run
- **Done:** `@claude (done 2026-04-06), <instruction>` — successfully executed
- **Skipped:** `@claude (skipped 2026-04-06: reason), <instruction>` — could not execute

The agent marks directives done (never deletes them), so the original instruction is preserved as documentation.

### Notes

- The agent interprets the directive in the context of the `##` section it appears in
- The agent may use vault data (People pages, JIRA, etc.) to fulfill the directive
- Do not place directives in the `## Related Items` section (auto-generated, will be overwritten)
- Maximum 5 directives per note per run
