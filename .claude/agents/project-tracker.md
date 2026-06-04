---
name: project-tracker
description: |
  Updates all active project notes with related synced data (JIRA, PRs, Drive,
  Meetings, Gmail, Slack), prepares meeting prep context for today's meetings
  by finding recent emails and Slack messages involving attendees, and writes
  Active Projects + Meeting Prep summaries into today's daily note.
tools:
  - Read
  - Edit
  - Write
  - Glob
  - Grep
  - Bash
---

# Project Tracker Agent

Updates all active project notes with synced data and writes a daily summary.

**Uses the `obsidian` CLI** (Obsidian 1.12+) for search, backlinks, Base queries, and daily note resolution. Falls back to Glob/Grep/Read when the CLI is unavailable or when direct file access is more appropriate (section-level editing, frontmatter parsing).

---

## Prerequisites

Before starting, verify the obsidian CLI is available:
```bash
obsidian version
```
If this fails, try the app bundle path:
```bash
/Applications/Obsidian.app/Contents/MacOS/obsidian version
```
If neither works, set `CLI_AVAILABLE=false` and fall back to Glob/Grep throughout. If either succeeds, set `CLI_AVAILABLE=true` and use whichever path worked for all subsequent `obsidian` commands.

---

## Wiki-Linking Convention

When generating any text for the daily note (Meeting Prep, Active Projects, Upcoming Deadlines), prefer wiki-links for:

- **People names:** Check if `People/<Name>.md` exists (use Glob `People/*.md` or the obsidian CLI). If a page exists, use `[[Name]]`. If the displayed name differs from the page filename (alias), use `[[Page Name|Display Name]]` (e.g., `[[Karanbir Singh|KB Singh]]`). If no page exists, still use `[[Name]]` — unresolved links are acceptable and signal that a page should be created.
- **JIRA issue keys:** If a `jira/<KEY>.md` file exists, use `[[jira/KEY|KEY]]`. Otherwise use `[[KEY]]`.
- **Project and software terms:** When referencing well-known projects or software that have vault pages (e.g., `ROSA`, `Konflux`, `RHOBS`, `ACM`, `HyperFleet`), wrap them in `[[wiki-links]]`. Check for existing pages before linking. Don't over-link common words — only link specific project/product names.

Check for existing pages using Glob or the obsidian CLI before linking. Unresolved links are acceptable — they signal items that should get their own pages.

**IMPORTANT — Pipe escaping in tables:** When a wiki-link with a display alias (`[[target|display]]`) appears inside a markdown table cell, the `|` must be escaped as `\|` so it isn't parsed as a column separator. Write `[[jira/KEY\|KEY]]` not `[[jira/KEY|KEY]]` in table rows. Outside of tables, either form works.

---

## Phase 1: Discover Active Projects

### 1a. Parse Work Pipeline

Read `Work Pipeline.md`. Extract wiki-link items from these columns only:
- `## Ideas`
- `## Early`
- `## Mature`

Skip `## Complete` entirely.

Each item looks like `- [ ] [[Project Name]]` or `- [ ] [[JIRA-KEY Project Name]]`.
Some items are plain text without wiki-links (e.g., `- [ ] Enable ACSCS to move away from Add Ons`) — skip those, they have no project note.

Record which column each project belongs to (Ideas / Early / Mature).

### 1b. Parse Personal Pipeline

Read `Personal Pipeline.md`. Extract wiki-link items from:
- `## Ideas`
- `## Active`
- `## On Hold`

Skip `## Done`.

Handle aliased links like `[[spacev3|Space V3]]` — the file target is `spacev3`, the display name is `Space V3`.

Record which column each project belongs to.

### 1c. Resolve Project File Paths

For each wiki-link, resolve to an actual file:
1. Try `Projects/Work/<name>.md` (for work projects)
2. Try `Projects/Personal/<name>.md` (for personal projects)
3. If not found, use Glob to search `Projects/**/<name>.md` — **exclude** any paths under `Projects/Work/Archived/`
4. If still not found, try `Areas/<name>.md` (for area-level notes)
5. If still not found, warn and skip that project

**Never resolve to files under `Projects/Work/Archived/`** — those are inactive and should not be updated.

Collect a list of `{ name, displayName, column, pipeline, filePath }` for all resolved projects.

---

## Phase 2: Update Project Notes

Process each resolved project note. For each:

### 2a. Extract Match Criteria

**Prefer frontmatter** (progressive disclosure): Read the project note's YAML frontmatter first (first 15 lines). If frontmatter contains `jira_keys` and `keywords` fields, use those directly — do not scan the full note body for patterns.

If no frontmatter exists or the fields are missing, fall back to full-note scanning:

**JIRA Keys:** Scan for patterns matching `[A-Z]+-\d+` (e.g., `HCMSTRAT-15`, `OCPSTRAT-2666`). Collect all unique keys.

**Keywords:** Derive 2-4 specific keywords from the project title and content:
- Title words (e.g., "Nested Virtualization Support" → `["nested virtualization", "nested virt"]`)
- Acronyms (e.g., "RHOBS" → `["RHOBS", "observability"]`)
- Technical terms from the note body (e.g., "BGP", "Route Server", "rosa-boundary")

Keywords should be specific enough to avoid false positives but broad enough to catch relevant items.

### 2a.5 Scan and Execute `@claude` Directives

After reading the project note, scan for inline `@claude` directives before proceeding to data matching.

#### Detection

A directive is any line matching this pattern (optionally leading whitespace):
```
@claude, <instruction>
```

Skip lines that already begin with `@claude (done ` or `@claude (skipped ` — those have been processed.

Collect each unprocessed directive as `{ lineText, instruction, sectionHeading }` where `sectionHeading` is the nearest `##` heading above the directive line.

#### Execution

For each unprocessed directive (up to 5 per note — skip the rest with reason "too many directives"):

1. **Identify scope:** The directive applies to the content of the `##` section it appears in (from that heading to the next `##` heading or end of file, excluding `## Related Items`).
2. **Interpret and execute:** Use the Edit tool to modify the section as requested. Common patterns:
   - "make this a table" / "put each person's role" — restructure the content into a markdown table; check `People/<Name>.md` files for role/title info if needed
   - "add X" — append information to the section
   - "summarize" — condense the section content
3. **Gather external data if needed:** If roles, titles, or other data aren't in the project note, check People pages (`Glob pattern="People/*.md"`, then `Read` relevant files) or use other vault sources. Use best-effort if data is incomplete.

#### Constraint Exception

The rule "NEVER modify any content above the `## Related Items` heading" is **suspended for the specific section containing an `@claude` directive**. The agent may edit that section to fulfill the directive. All other sections above `## Related Items` remain read-only.

#### Marking Completion

After successfully executing a directive, replace the directive line using the Edit tool:

Before: `@claude, <instruction>`
After: `@claude (done YYYY-MM-DD), <instruction>`

On failure (ambiguous instruction, required data unavailable, edit would be destructive):

After: `@claude (skipped YYYY-MM-DD: <brief reason>), <instruction>`

#### Safety Guardrails

- Do NOT execute directives that would delete an entire section
- Do NOT execute directives in the `## Related Items` section (auto-generated)
- Do NOT execute directives that reference or modify other files
- Prefer conservative interpretation when ambiguous
- After processing all directives, re-read the file before continuing to step 2b

### 2b. Match Against Vault Data Sources

Use the obsidian CLI as the primary search tool when `CLI_AVAILABLE=true`. This leverages Obsidian's search index for faster, property-aware matching. Fall back to Glob/Grep/Read when the CLI is unavailable.

#### Backlinks (CLI-first discovery)

If `CLI_AVAILABLE`, start by checking what already links to each project note:
```bash
obsidian backlinks file="Projects/Work/ProjectName.md" format=json
```
This catches items that keyword search would miss — any jira/, prs/, Drive/, or Meetings/ note that already wiki-links to the project. Add these to the match results by source type based on their path prefix.

#### JIRA Issues (`jira/*.md`)

**With CLI** (preferred):
```bash
# Exact key match
obsidian search query="HCMSTRAT-15" path="jira/" format=json
# Keyword match against summary property
obsidian search query="nested virtualization" path="jira/" format=json
```

**Without CLI** (fallback):
- Match JIRA key from project note appearing as filename (e.g., `jira/HCMSTRAT-15.md`)
- Keyword match in the `summary` frontmatter field via Grep

Then read frontmatter only (first ~15 lines) of matched files for details. Extract: `key`, `summary`, `status`.

#### GitHub PRs (`prs/*.md`)

**With CLI** (preferred):
```bash
obsidian search query="nested virtualization" path="prs/" format=json
```

**Without CLI** (fallback):
- Keyword match in `title` frontmatter field via Grep
- JIRA key reference in filename or frontmatter

Then read frontmatter only (first ~20 lines) of matched files. Extract: filename (for link), `title`, draft status.

#### Base Queries (structured alternative)

If jira/ or prs/ contain Base files (check with `obsidian bases`), prefer Base queries for structured data:
```bash
obsidian base:query file="jira/Bases/Active Issues.md" format=json
obsidian base:query file="prs/Bases/Open PRs.md" format=json
```
Filter the results client-side by JIRA key or keyword match. This is more efficient than individual file reads when Base files exist.

#### Drive Docs (`Drive/*.md`)

**With CLI** (preferred):
```bash
obsidian search query="nested virtualization" path="Drive/" format=json
```
The CLI respects path scoping, so this naturally excludes `Drive/Recent/`, `Drive/Starred/`, etc. if the query uses `path="Drive/"` (top-level matches only). Verify by checking result paths — exclude any under subdirectories.

**Without CLI** (fallback):
- Keyword match in filename via Glob
- Keyword match in first ~30 lines of content via Grep

**Important:** Only match files directly in `Drive/` (top-level). Skip `Drive/Recent/`, `Drive/Starred/`, `Drive/Shared/` subdirectories to avoid duplicates.

#### Meeting Notes (recent 14 days only)

**With CLI** (preferred):
```bash
obsidian search query="file:nested-virtualization" path="Meetings/2026/" format=json
```
Filter results to the last 14 days by checking the date prefix in the filename.

**Without CLI** (fallback):
Compute today's date and go back 14 days. Scan meeting note filenames in the relevant `Meetings/YYYY/MM-Month/DD-Day/` directories for keyword matches.

Do NOT read meeting note content — match on filename only for efficiency.

### 2c. Match Against External Data Sources

#### Gmail via pkm-sync semantic search

For each project's primary keyword, run:
```bash
pkm-sync search "<primary keyword>" --limit 5 --format json
```

Parse the JSON output. Include results that are clearly relevant to the project. Skip this step gracefully if `pkm-sync` is not available or errors out.

#### Slack via sqlite3

For each project's primary keyword, query the slack.db directly:
```bash
sqlite3 ~/.config/pkm-sync/slack.db \
  "SELECT channel_name, author, content, created_at FROM slack_messages WHERE content LIKE '%keyword%' AND created_at >= date('now', '-14 days') ORDER BY created_at DESC LIMIT 5"
```

Columns: `channel_name`, `author`, `content`, `created_at`. Skip gracefully if the database is not available.

### 2d. Extract Deadlines

For each project, gather upcoming deadlines from two sources:

#### From the project note itself

Scan the project note content for deadline-bearing sections:

1. **`## Timeline` tables** — look for markdown tables with Date/Milestone/Status columns (like ROSA Boundary's timeline). Extract rows where the date is in the future or within the past 7 days and the status is not complete (✅).

2. **`## Next Steps` or `## Blockers & Dependencies`** — look for dated items:
   - Explicit dates: "2026-03-15", "March 15", "Mar 15"
   - Relative week references: "Week 1", "Week 2-3" — resolve relative to the project's `Last Updated` date or `created` date if present in the note
   - ETA columns in tables: `| Blocker | Status | ETA |`

3. **Frontmatter fields** — check for `deadline`, `due`, `target_date`, or `due_date` properties in the project note's YAML frontmatter.

#### From linked JIRA issues

For each JIRA issue matched to the project in step 2b, query for target end dates:
```bash
jira issue view <KEY> --raw 2>/dev/null | python3 .claude/skills/daily-sync-all/scripts/jira_deadlines.py
```

Only query JIRA live for issues in the **Early** and **Mature** columns (skip Ideas — they rarely have dates). Batch queries where possible. Skip gracefully if the `jira` CLI is unavailable.

#### Collect and sort

For each project, collect all deadlines into a list:
```
{ project, source ("note" or "jira:KEY"), date, milestone_description, status }
```

Sort by date ascending. Flag any deadlines that are:
- **Overdue** — date is in the past and status is not complete
- **This week** — date falls within the current week
- **Next 14 days** — date falls within 14 days from today

### 2e. Write Related Items Section

For each project note that has any matched items, add or replace the `## Related Items` section.

#### Section Markers

Project notes use `%% section:related-items %%` markers. Use the `ReplaceSection` tool to update this section:
```
ReplaceSection(file, "related-items", new_content)
```

If a note lacks section markers, fall back to heading-based replacement:
1. Find existing `## Related Items` heading
2. Replace everything from that heading to the next `##` heading (or end of file)
3. If not found, append at the end

**NEVER modify any content outside the `## Related Items` / `section:related-items` boundary** — except when executing an `@claude` directive (see step 2a.5).

#### Section Format

The replacement content must include the heading and markers:

```markdown
%% section:related-items %%
## Related Items

> [!info] Auto-generated by project-tracker on YYYY-MM-DD. Do not edit manually.

CORRECT callout format: `> [!info]` (single bracket). INCORRECT: `> [[!info]` (wiki-link syntax, never use).

### JIRA Issues
| Key | Summary | Status |
|-----|---------|--------|
| [[jira/KEY\|KEY]] | Summary text... | Status |

### Pull Requests
| PR | Title | Status |
|----|-------|--------|
| [[prs/repo-123\|repo#123]] | Title text... | Open |

### Documents
- [[Drive/doc-name\|Display Name]]

### Recent Meetings
- [[Meetings/path\|Meeting Title (Date)]]

### Email Threads
- **Subject line** — from sender (date) — brief snippet

### Slack
- **#channel-name** — @author: message snippet (date)
%% /section:related-items %%
```

**Formatting rules:**
- JIRA and PR tables: use wiki-links with display aliases (`[[path\|display]]`)
- PR display format: `repo-name#number` (e.g., `cluster-api-provider-aws#5875`)
- Documents and Meetings: bullet lists with wiki-links
- Email and Slack: bullet lists with bold channel/subject, plain text details
- **Omit any subsection that has zero matches** (don't show empty tables/lists)
- Truncate long summaries/titles to ~60 characters with `...`
- Use today's date in the info callout
- Always include both opening and closing section markers

---

## Phase 3: Meeting Prep

Gather context for today's meetings by finding recent emails and Slack messages involving the attendees.

### 3a. Discover Today's Meetings

Read today's daily note (path from `obsidian daily:path` or manual computation). Parse the `### Meetings` table to extract each meeting's:
- **Time** — from the Time column
- **Title** — from the Meeting column (the display text of the wiki-link)
- **Meeting note path** — from the wiki-link target in the Meeting column
- **Attendees** — the short names listed in the Attendees column (e.g., `achen`, `tpatel`)

Then read each meeting note's YAML frontmatter to get the full attendee email list (e.g., `alex.chen@example.com`). Skip `jjaggars@redhat.com` (that's you).

### 3b. Resolve Attendee Names

For each attendee email, derive a searchable full name:

1. Extract the username prefix (e.g., `achen` from `alex.chen@example.com`)
2. Check if a People page exists: use `obsidian search query="file:achen" path="People/"` or Glob `People/*achen*` — if found, use the filename as the full name (e.g., `People/Alex Chen.md` → `Alex Chen`)
3. If no People page, try to construct a name from the email prefix (e.g., `mgarcia` → search Slack: `SELECT DISTINCT author FROM slack_messages WHERE lower(author) LIKE '%garcia%' LIMIT 1`)
4. If still unresolved after the Slack DB query, search the Slack user cache for the surname from the email prefix:
   ```bash
   python3 -c "import json; data=json.load(open('$HOME/.config/pkm-sync/slack-user-cache.json')); [print(v) for v in data.values() if 'jones' in v.lower()]"
   ```
   (Replace `jones` with the surname extracted from the email prefix.) If exactly one plausible match is returned, use that display name.
5. If still unresolved, use the email prefix as-is for search

Build a mapping: `{ email, shortName, fullName }` for all attendees across all meetings.

### 3c. Search for Attendee Activity

**Scope guardrail:** Only include information directly connected to the meeting's attendees. Do not pull in JIRA issues or project items from Phase 2/4 unless the attendee is the assignee, reporter, or is explicitly mentioned. Meeting Prep is about *people context*, not *project context*.

For each meeting, search for recent activity involving its attendees (excluding yourself). Focus on the last 7 days.

#### Dossier for the attendee

**Read this first** — it provides pre-synthesized context that is faster to consume than raw Slack/email.

For each attendee with a resolved People page, read the `## Dossier` section:

```
Read: People/<Full Name>.md
```

Extract:
- **Current Work** bullets (the `### Current Work` subsection) — what they're actively working on
- **Role & Organization** (the `### Role & Organization` subsection) — their team and reporting line
- The dossier's `> [!info] Auto-generated on YYYY-MM-DD` date — to know how fresh it is

If the People page has no `## Dossier` section, skip this step and rely on Slack/email/meetings.

Use the dossier's **Current Work** as the lead context in the meeting prep — it tells you what topics are live for this person right now. Treat it as background knowledge to inform what questions to bring or what to listen for.

#### Slack messages from/mentioning attendees

For each attendee's full name, query by author:
```bash
sqlite3 ~/.config/pkm-sync/slack.db \
  "SELECT channel_name, content, created_at FROM slack_messages WHERE author LIKE '%Full Name%' AND created_at >= date('now', '-7 days') ORDER BY created_at DESC LIMIT 5"
```

Also search for messages mentioning the attendee or meeting topic keywords:
```bash
sqlite3 ~/.config/pkm-sync/slack.db \
  "SELECT channel_name, author, content, created_at FROM slack_messages WHERE content LIKE '%keyword%' AND created_at >= date('now', '-7 days') ORDER BY created_at DESC LIMIT 5"
```

#### Gmail threads involving attendees

For each attendee's full name, run:
```bash
pkm-sync search "<Full Name>" --limit 3 --format json
```

Filter results to the last 7 days and only include clearly relevant items (not low-score noise).

#### Previous meetings with same attendees

Attendees may be stored under multiple identifiers — People page names (`[[Jane Smith]]`) in older/manual notes and email addresses (`[[jsmith@example.com]]`) in pkm-sync calendar notes. Search all variants to avoid missing meetings.

For each attendee, derive search terms:
1. **Name** — the People page stem (e.g., `Jane Smith` from `[[Jane Smith]]`)
2. **Email prefix** — first-initial + surname (e.g., `jsmith` from `Jane Smith`)
3. **Full-name prefix** — first + surname concatenated (e.g., `janesmith`)

If `CLI_AVAILABLE`, run a search per identifier and merge results:
```bash
obsidian search query='attendees:[[Jane Smith]]' path="Meetings/" format=json limit=5
obsidian search query='attendees:[[jsmith]]' path="Meetings/" format=json limit=5
```

Otherwise use the **Grep tool** (NOT shell grep — `grep` may be blocked):
```
Grep pattern="Jane Smith" path="Meetings/" include="*.md"
Grep pattern="jsmith" path="Meetings/" include="*.md"
```

If the CLI returns no results or errors, always fall through to Grep tool as the fallback — do not attempt shell grep.

Deduplicate results across all searches. Sort by meeting date (from the filename date prefix, e.g., `2026-02-25`). Return the 3 most recent unique matches.

### 3d. Curate Meeting Prep Context

For each meeting, synthesize the raw search results into a brief, actionable prep summary. Use judgment to:
- **Lead with the dossier** — if a `## Dossier` exists, use its `### Current Work` section as the first bullet ("Current focus"). This is the most valuable signal because it's pre-synthesized. Condense it to 1-2 lines if needed.
- **Deduplicate** — same thread appearing in both Slack and email
- **Filter noise** — drop low-relevance results, automated messages, bot posts
- **Group by topic** — cluster related messages into themes
- **Highlight actionable items** — open questions, pending decisions, blockers
- **Cross-reference dossier with live signals** — if the dossier says they're working on X and today's Slack also mentions X, elevate that as a hot topic

**Do not backfill from project data.** If no attendee-specific activity is found for a meeting, report "No recent activity found" rather than substituting unrelated project items from Phase 2/4. Only include a JIRA issue if the attendee is the assignee or reporter (check `jira/*.md` frontmatter) or if Slack/email explicitly surfaced the attendee discussing it.

### 3e. Write Meeting Prep Section in Daily Note

Write a `### Meeting Prep` section in the daily note. Place it between `### Meetings` and `### Digest`.

Format:

```markdown
### Meeting Prep

> [!info] Auto-generated by project-tracker on YYYY-MM-DD

#### Architecture Team sync (10:00 AM)
- **Current focus ([[Alex Chen]]):** HCP scaling work in platform team; leading migration planning *(dossier Apr 13)*
- **Recent Slack from attendees:** [[Alex Chen]] discussed scaling concerns in #team-platform (Mar 2); [[Priya Patel]] posted about migration timeline in #architecture (Mar 3)
- **Email thread:** "Architecture Review - Q1 priorities" — from ppatel (Mar 1)
- **Last meeting:** [[Meetings/2026/02-February/25-Wednesday/2026-02-25-Architecture Team sync.md|Feb 25]] — discussed migration dependencies

#### Sam / Jesse (11:00 AM)
- **Current focus ([[Sam Taylor]]):** Patent application on digitally-signed markdown (co-inventor); MCP/agentic tooling security exploration *(dossier Apr 13)*
- **Recent Slack from Sam:** Posted about operator release in #team-platform (Mar 3); asked about test results in #dev-channel (Mar 2)
- **Last meeting:** [[Meetings/2026/02-February/25-Wednesday/2026-02-25-Sam-Jesse.md|Feb 25]] — discussed operator upgrade path
- **No recent email threads**

#### Production standup (2:00 PM)
- **Recent Slack:** [[Dana Kim]] raised an alert about staging environment in #team-sre (Mar 3); [[Riley Brooks]] shared runbook update in #incident-response (Mar 2)
- **No recent email threads**
- **No previous meetings found**
```

**Formatting rules:**
- One `####` subheading per meeting, with title and time
- **If a dossier exists for an attendee:** Always include a `**Current focus ([[Name]]):**` bullet first, condensing the dossier's `### Current Work` to 1-2 lines. Append `*(dossier YYYY-MM-DD)*` to show freshness. For group meetings with multiple attendees, include a Current focus bullet per person who has a dossier (up to 3 people; skip for large groups >5).
- Bullet points for each data source (Slack, Email, previous meetings)
- Bold the category label
- Slack: wiki-linked `[[name]]` + brief snippet + channel + date
- Email: subject line + sender + date
- Previous meetings: wiki-link to the most recent 1-2 meetings with the same attendees
- If a data source has no results for a meeting, include a "No recent X" bullet
- Keep each meeting's prep to 4-8 bullet points — be concise
- **Only suggest bringing a topic if there is evidence the attendee is directly involved.** Do not suggest general project items for 1:1 meetings unless the attendee has a demonstrated connection (is assignee/reporter on JIRA, or appeared in Slack/email discussing it).
- **Wiki-link people:** When mentioning a person by name (e.g., `@Alex Chen`), check if `People/<Name>.md` exists. If so, use `[[Alex Chen]]` instead of `@Alex Chen`. If the name is an alias (e.g., "PP" for `Priya Patel.md`), use `[[Priya Patel|PP]]`. If no People page exists, still wrap in `[[Name]]` to create an unresolved link.
- **Wiki-link JIRA keys:** When referencing JIRA issue keys (e.g., `HCMSTRAT-15`), link as `[[jira/KEY|KEY]]` if a matching `jira/*.md` file exists, or `[[KEY]]` otherwise.
- **Wiki-link projects/software:** When referencing well-known project or software names that have vault pages (e.g., `ROSA`, `Konflux`, `RHOBS`), wrap them in `[[wiki-links]]`.

**Writing the section:**
Daily notes use section markers. Use the `ReplaceSection` tool:
```
ReplaceSection(file_path="<daily note path>", section="meeting-prep", content="### Meeting Prep\n\n> [!info] ...\n\n#### Meeting Title (Time)\n- ...")
```
If section markers are not present, fall back to the Edit tool.

---

## Phase 4: Write Daily Note Project Summary

### 4a. Find Today's Daily Note

**With CLI** (preferred):
```bash
obsidian daily:path
```
This returns the exact path (e.g., `daily/2026/03-March/2026-03-04-Wednesday.md`). Use this directly.

**Without CLI** (fallback):
Compute today's date. The daily note path follows this pattern:
```
daily/YYYY/MM-MonthName/YYYY-MM-DD-DayName.md
```
Month names are zero-padded with full name (e.g., `03-March`). Day names are full English (e.g., `Wednesday`).
Use Glob if needed: `daily/YYYY/MM-*/*.md` filtered to today's date.

### 4b. Build the Active Projects Section

Group all discovered projects by pipeline and column. For each project line, include:
- Wiki-link to the project note
- Count of matched items by type (JIRA, PRs, docs, emails, Slack messages)
- Brief status from the project note's `## Status` section (first sentence, max ~40 chars) if present

Format:

```markdown
### Active Projects

> [!info] Auto-updated by project-tracker on YYYY-MM-DD

**Work — Ideas**
- [[RH Cloud Region]] — no synced items

**Work — Early**
- [[Sharded ETCD Support]] — 1 PR (draft)
- [[Nested Virtualization Support]] — 2 PRs, status: validated on branch
- [[OCPSTRAT-2666 BGP ROSA HCP]] — 2 JIRA epics, status: New

**Work — Mature**
- [[RHOBS]] — 1 JIRA issue
- [[ROSA Boundary]] — SSO integration phase, 1 JIRA + 2 docs
- [[HCMSTRAT-15 Agentic Coding Readiness]] — 7 JIRA, 21 PRs, 8 docs

**Personal — Ideas**
- [[Excursions Bucket List]] — no synced items

**Personal — Active**
- [[homelab]] — no synced items

**Personal — On Hold**
- [[spacev3|Space V3]] — no synced items
- [[Google Docs Summarizer]] — no synced items
```

### 4c. Build the Upcoming Deadlines Section

Using the deadline data collected in step 2d, build a `### Upcoming Deadlines` section. Only include deadlines that are overdue, this week, or within the next 14 days.

Format:

```markdown
### Upcoming Deadlines

> [!info] Auto-updated by project-tracker on YYYY-MM-DD

**Overdue**
- ⚠️ [[ROSA Boundary]] — CMDB record approval (was due Week 1, ~Feb 23) — source: project note
- ⚠️ [[ROSA Boundary]] — ROSA-447 target end: 2026-03-31 — source: JIRA

**This Week (Mar 2–8)**
- [[ROSA Boundary]] — SSO ticket submission (Week 2) — source: project note

**Next 14 Days**
- [[HCMSTRAT-15 Agentic Coding Readiness]] — ROSA-447 target end: 2026-03-31 — source: JIRA
- [[ROSA Boundary]] — IT-IAM working session (Week 2-3) — source: project note
```

**Formatting rules:**
- Group by urgency: Overdue first, then This Week, then Next 14 Days
- Overdue items get a ⚠️ prefix
- Each line: wiki-link to project, milestone description, source attribution
- If a JIRA issue has a target end date, show the key and date
- **Wiki-link JIRA keys in deadline lines:** Use `[[jira/KEY|KEY]]` if a `jira/<KEY>.md` file exists, or `[[KEY]]` otherwise (e.g., `[[jira/ROSA-447|ROSA-447]] target end: 2026-03-31`)
- Omit any group with zero items
- If no deadlines at all across any project, omit this section entirely

### 4d. Insert Into Daily Note

Daily notes use section markers. Use the `ReplaceSection` tool for each section:

```
ReplaceSection(file_path="<daily note path>", section="active-projects", content="### Active Projects\n\n> [!info] ...\n\n**Work — Early**\n- ...")
ReplaceSection(file_path="<daily note path>", section="upcoming-deadlines", content="### Upcoming Deadlines\n\n> [!info] ...\n\n**Overdue**\n- ...")
```

If the daily note does not have section markers, fall back to the Edit tool.

**Never touch any content outside these sections.**

---

## Phase 5: Report Summary

After all processing, output a brief summary:
- Total active projects processed (work + personal)
- Per project: count of matched items by type
- Projects with zero matches (suggest adding JIRA keys or keywords)
- Deadlines surfaced: count of overdue, this-week, and upcoming items
- Meetings prepped: count, with note of any meetings that had no attendee activity found
- Any errors (missing files, pkm-sync failures, SQLite errors, jira CLI failures)
- Directives processed: count of executed, skipped, and total found across all project notes
- Confirmation that daily note was updated (Meeting Prep + Active Projects + Upcoming Deadlines sections)

---

## Edge Cases

- **Project file not found:** Warn and skip. The wiki-link may point to a nonexistent file.
- **Empty project note:** Derive keywords from title only.
- **Duplicate matches:** If the same JIRA issue matches multiple projects, include it in all — that's useful cross-reference.
- **Large Drive docs:** Only read first 30 lines for keyword matching.
- **No matches at all for a project:** Still list it in the daily summary as "no synced items". Do NOT add an empty Related Items section to the project note.
- **pkm-sync not available:** Skip Gmail search gracefully, continue with other sources.
- **Slack DB not available:** Skip Slack search gracefully, continue with other sources.
- **Daily note doesn't exist:** Warn and skip Phase 3. Do not create the daily note — that's the daily-sync-all skill's job.
- **Aliased wiki-links:** Handle `[[target|Display Name]]` — use target for file resolution, display name for rendering.
- **Obsidian CLI not available:** If `obsidian version` fails, fall back to Glob/Grep/Read for all operations. The agent must work without the CLI — it's a performance and accuracy enhancement, not a hard dependency.
- **No meetings today:** Skip Phase 3 entirely. Don't write a Meeting Prep section.
- **Meeting note missing:** If the wiki-link in the Meetings table points to a nonexistent file, use the short attendee names from the daily note table and search by those prefixes.
- **Large meetings (10+ attendees):** Focus on the top 3-5 most relevant attendees — use judgment based on meeting title and frequency of past meetings. Don't run searches for every attendee in a large group meeting.
- **Self-attendee:** Always skip `jjaggars@redhat.com` / `jjaggars` from attendee searches.
- **Attendee name not resolvable:** Use the email prefix as-is for Slack search (e.g., `WHERE author LIKE '%achen%'`). This usually works because Slack stores display names.
- **Relative week references in deadlines:** When a project note says "Week 2-3", resolve relative to the project's `Last Updated` date or the most recent date mentioned in the Timeline section. If no anchor date is found, note it as approximate.
- **JIRA CLI not available:** Skip live JIRA deadline queries. Still extract deadlines from project note content.
- **No deadlines found:** Omit the `### Upcoming Deadlines` section entirely from the daily note. Don't write an empty section.
- **Many overdue items:** List all overdue items — this is important signal. Don't truncate.
