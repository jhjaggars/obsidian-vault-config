---
name: project-sync
description: |
  Enriches active project notes with a Related Items section linking to relevant
  JIRA issues, GitHub PRs, Drive docs, and recent meeting notes. Scans synced
  data across folders and uses keyword/key matching to connect the dots.
  Use this skill when the user wants to:
  - Run /project-sync
  - Update project notes with related work items
  - See what synced data relates to each active project
  - Enrich project notes with linked JIRA, PRs, Drive docs, and meetings
---

# Project Sync Skill

Scans active projects from `Work Pipeline.md` and enriches each project note with a `## Related Items` section linking to relevant synced data (JIRA issues, GitHub PRs, Drive docs, and recent meeting notes).

**Uses the `obsidian` CLI** (Obsidian 1.12+) for search, backlinks, and Base queries when available. Falls back to Glob/Grep/Read when the CLI is unavailable.

## When to Use This Skill

Trigger when the user asks to:
- "Sync my projects" / "project sync"
- "Update project notes with related items"
- "What's related to my active projects?"
- "Link JIRA/PRs/docs to my projects"

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

## Workflow

### Step 1: Parse Work Pipeline

Read `Work Pipeline.md`. Extract project names from the `## Early` and `## Mature` columns only (skip Ideas and Complete).

Each item is a wiki-link like `[[Platform Autoscaling Support]]` or `[[PROJ-15 Agentic Coding Readiness]]`. Resolve each to its file path. Project notes live under `Projects/Work/` — some may be in subdirectories. Use Glob to find each file if the direct path doesn't exist.

### Step 2: Build Match Rules Per Project

For each project note, read its content and extract matching criteria:

#### JIRA Keys (exact match)
Scan the note content for JIRA issue key patterns matching `[A-Z]+-\d+` (e.g., `PROJ-123`, `FEAT-456`, `BUG-789`). Collect all unique keys found. These become exact-match criteria against `jira/*.md` filenames and content.

#### Keywords (fuzzy match)
Derive 2-4 keywords from the project title and content. Use your judgment:
- Project title words (e.g., "Platform Autoscaling Support" → `["autoscaling", "platform scaling"]`)
- Acronyms and short names (e.g., "OBSV" → `["OBSV", "observability"]`)
- Technical terms from the note body (e.g., "BGP", "Route Server", "api-gateway")

Keywords should be specific enough to avoid false positives but broad enough to catch relevant items.

### Step 3: Match Synced Data to Projects

For each project, scan these sources. Use the obsidian CLI as the primary search tool when `CLI_AVAILABLE=true`. Fall back to Glob/Grep/Read when the CLI is unavailable.

#### Backlinks (CLI-first discovery)

If `CLI_AVAILABLE`, start by checking what already links to each project note:
```bash
obsidian backlinks file="Projects/Work/ProjectName.md" format=json
```
This catches items that keyword search would miss — any jira/, prs/, Drive/, or Meetings/ note that already wiki-links to the project. Add these to the match results by source type based on their path prefix.

#### 3a. JIRA Issues (`jira/*.md`)

**With CLI** (preferred):
```bash
# Exact key match
obsidian search query="PROJ-123" path="jira/" format=json
# Keyword match against summary
obsidian search query="nested virtualization" path="jira/" format=json
```

**Without CLI** (fallback):
Match by:
- JIRA key appearing in the project note (exact filename match, e.g., project mentions `PROJ-123` → match `jira/PROJ-123.md`)
- `project` frontmatter field matching a JIRA project prefix from the project note
- Keyword match in the `summary` frontmatter field

Read frontmatter only (first ~15 lines) for efficiency. Extract: `key`, `summary`, `status`, `updated`.

#### 3b. GitHub PRs (`prs/*.md`)

**With CLI** (preferred):
```bash
obsidian search query="nested virtualization" path="prs/" format=json
```

**Without CLI** (fallback):
Match by:
- Keyword match in `title` frontmatter field
- JIRA key reference in filename or content
- Repository name match if the project references specific repos

Read frontmatter only (first ~20 lines). Extract: filename (for link), `title`, `repo`, draft status, CI status.

#### 3c. Drive Docs (`Drive/*.md`)

**With CLI** (preferred):
```bash
obsidian search query="nested virtualization" path="Drive/" format=json
```
Verify result paths — exclude any under `Drive/Recent/`, `Drive/Starred/`, `Drive/Shared/` subdirectories to avoid duplicates.

**Without CLI** (fallback):
Match by:
- Keyword match in filename
- Keyword match in first ~30 lines of content

**Important:** Only match files in `Drive/` (top-level) to avoid duplicates with `Drive/Recent/`, `Drive/Starred/`, etc. which are symlinks/copies. If a file appears in both `Drive/` and `Drive/Recent/`, prefer the `Drive/` path.

Extract: filename (for link), title from content.

#### 3d. Meeting Notes (recent 14 days only)

**With CLI** (preferred):
```bash
obsidian search query="file:nested-virtualization" path="Meetings/2026/" format=json
```
Filter results to the last 14 days by checking the date prefix in the filename.

**Without CLI** (fallback):
Compute the date range (today minus 14 days). Scan meeting note filenames in the relevant `Meetings/YYYY/MM-Month/DD-Day/` directories for keyword matches in the filename.

Do NOT read meeting note content — match on filename only for efficiency.

#### 3e. Semantic Search (optional, if pkm-sync is available)
For each project, run:
```bash
pkm-sync search "<primary project keyword>" --limit 5
```

Use results to catch items missed by keyword matching. Only include results that are clearly relevant (use judgment). Skip this step if `pkm-sync` is not available or errors.

### Step 4: Update Project Notes with Related Items Section

For each project note that has matched items, add or replace a `## Related Items` section.

#### Idempotency Rules
1. Find existing `## Related Items` heading in the file
2. If found, replace everything from `## Related Items` to the next `##` heading (or end of file)
3. If not found, append the section at the end of the file
4. **Never modify any content above the `## Related Items` heading**

#### Section Format

```markdown
## Related Items

> [!info] Auto-generated by /project-sync on YYYY-MM-DD. Do not edit manually.

### JIRA Issues
| Key | Summary | Status |
|-----|---------|--------|
| [[jira/PROJ-123\|PROJ-123]] | Implement autoscaling support... | In Progress |

### Pull Requests
| PR | Title | Status |
|----|-------|--------|
| [[prs/your-repo-42\|your-repo#42]] | feat: add platform autoscaling... | Draft |

### Documents
- [[Drive/project-architecture\|project-architecture]]
- [[Drive/Engineering-Weekly-Status\|Engineering Weekly Status]]

### Recent Meetings
- [[Meetings/2026/02-February/27-Thursday/2026-02-27-Some Meeting\|Some Meeting]]
```

**Formatting rules:**
- JIRA and PR tables: use wiki-links with display aliases (`[[path\|display]]`)
- PR display format: `repo-name#number` (e.g., `cluster-api-provider-aws#5875`)
- Documents and Meetings: use bullet lists with wiki-links
- Omit any subsection that has zero matches (don't show empty tables)
- Truncate long summaries/titles to ~60 characters with `...`
- Use today's date in the callout

### Step 5: Report to User

After processing all projects, summarize:
- How many active projects were processed
- Per project: how many items were found in each category
- Any projects that had zero matching data (suggest adding JIRA keys or keywords to those notes)
- Any errors encountered (e.g., missing project files, pkm-sync failures)

---

## Edge Cases

- **Project file not found:** Warn the user and skip that project. The wiki-link in Work Pipeline may point to a file that doesn't exist yet.
- **Empty project note:** If a project note has minimal content (like just a `# Title`), derive keywords from the title only.
- **Duplicate matches:** If the same JIRA issue matches multiple projects, include it in all of them — that's useful cross-reference information.
- **Large Drive docs:** Only read the first 30 lines of Drive docs for keyword matching. Don't read entire documents.
- **No matches at all:** Still add the `## Related Items` section with the callout noting no items were found, so the user knows it was checked.

---

## Headless Mode (Python Script)

A standalone Python script can run project sync without the LLM:

```bash
uv run .claude/skills/project-sync/scripts/project_sync.py /path/to/vault
```

The script uses deterministic keyword matching instead of LLM judgment. To improve matching quality, add a `keywords:` field to project note frontmatter:

```yaml
---
keywords: ["BGP", "Route Server", "routeAdvertisements"]
---
```

Without explicit keywords, the script derives them from the project title (splitting on words, removing stop words, generating bigrams).

The script is integrated into `sync_all_sources.sh` as step 4.5 and runs automatically during daily sync.

## Integration with daily-sync-all

This skill can be called standalone (`/project-sync`), via the headless Python script, or as part of the daily-sync-all workflow (step 4.5 in `sync_all_sources.sh`).
