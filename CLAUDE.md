# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is an Obsidian vault for personal knowledge management, including meeting notes, daily notes, documentation, and a Zettelkasten (ZK) system. The vault uses several Obsidian plugins including Templater, Dataview, and Excalidraw.

## Vault Structure

- **Meetings/**: Meeting notes organized by `YYYY/MM-Month/DD-Day/YYYY-MM-DD-Title.md` format
  - Each meeting note has YAML frontmatter with `attendees` array containing wiki-links to people
  - Meeting templates automatically include a dataview query showing previous meetings with same attendees
- **daily/**: Daily notes organized by `YYYY/MM-Month/` with files named `YYYY-MM-DD-Day.md`
  - Generated from `Templates/daily.md` with sections: Meetings, Todo, Misc
  - Includes dataview queries showing notes created/modified each day
- **People/**: Person pages (using `Templates/Person.md`)
- **Reference/**: Reference material to consult when relevant — read specific files on demand rather than all at once. Current contents:
  - `ship-help.md` — How to use the `@ship-help` Slack AI bot for OpenShift process, pipeline, and technical questions (channels, consent, data sources, example queries, teaching it)
- **Personal/**: Personal notes including travel, family, health, hobbies, and side projects
- **docs/**: Documentation and longer-form writing
- **SOP/**: Standard Operating Procedures
- **Projects/**: Project-related notes
- **Templates/**: Templater templates for different note types
- **scripts/**: Templater JS modules (only `buildPageAndLink.js` — Python scripts moved to `.claude/skills/`)
- **dataviewscripts/**: DataviewJS scripts

## Key Plugins & Scripts

### Templater Configuration
- Templates folder: `Templates/`
- User scripts folder: `scripts/`
- Folder templates automatically apply to new files:
  - `Meetings/` → `Templates/Meeting.md`
  - `People/` → `Templates/Person.md`

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

Project notes in `Projects/` support inline `@claude` directives — natural-language instructions that the project-tracker agent picks up and executes during its daily sync run (step 6 of the pipeline).

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

## Learned Patterns

Check `.claude/memory/` for learned patterns and preferences that should be applied when working in this vault. These include conventions for project updates, callout formats, and other workflows discovered through use.

## Git Workflow

This is a git repository tracking the vault contents. The `.gitignore` excludes `.obsidian/*` metadata.
