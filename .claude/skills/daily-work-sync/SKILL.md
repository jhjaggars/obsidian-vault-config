---
name: daily-work-sync
description: Sync JIRA issues and GitHub pull requests to Obsidian as individual Base notes with consistent frontmatter properties. Use this skill when the user wants to update their daily work tracking, sync JIRA issues to Obsidian, sync GitHub PRs to Obsidian, or create queryable Bases for work items. Automatically creates separate notes for each issue/PR in jira/ and prs/ folders with properties for filtering and visualization.
---

# Daily Work Sync

Syncs your JIRA issues and GitHub pull requests to Obsidian as individual notes optimized for [Obsidian Bases](https://help.obsidian.md/bases). Each work item becomes a separate note with consistent frontmatter properties, enabling powerful querying, filtering, and visualization.

## Overview

This skill queries JIRA and GitHub to find all work items related to you, then creates/updates individual notes in your vault:

- **JIRA issues** → `jira/` folder with properties: key, summary, type, status, priority, assignee, reporter, project, relationship, etc.
- **GitHub PRs** → `prs/` folder with properties: number, title, repo, category, draft status, updated date, etc.

Each note includes:
- Complete frontmatter for Bases querying
- Formatted content with links back to the source
- Automatic cleanup of closed/stale items

## When to Use This Skill

Trigger this skill when the user asks to:
- "Update my daily work tracking"
- "Sync my JIRA issues to Obsidian"
- "Pull in my GitHub PRs"
- "Refresh my work items"
- "Show me what I'm working on"

## How It Works

### Step 1: Run the Sync Script

Execute the sync script with the vault path using `uv run`:

```bash
uv run scripts/sync_daily_work.py /path/to/vault
```

For this vault specifically:

```bash
uv run $VAULT_DIR/.claude/skills/daily-work-sync/scripts/sync_daily_work.py $VAULT_DIR
```

### Step 2: What Gets Created

The script queries and creates:

**JIRA Issues** (`jira/` folder):
- Queries for issues where you are: assigned, reporter, watcher, or commenter
- Creates notes like `jira/PROJ-123.md`, `jira/PROJ-456.md`
- Each note has frontmatter properties:
  ```yaml
  ---
  key: "PROJ-123"
  summary: "Support min-replicas=0 with autoscaling"
  type: "Story"
  status: "In Progress"
  priority: "Undefined"
  project: "PROJ"
  assignee: "Alice Smith"
  reporter: "Alice Smith"
  created: "2025-10-23"
  updated: "2025-11-20"
  url: "https://your-org.atlassian.net/browse/PROJ-123"
  relationship: "assigned"
  source: "jira"
  ---
  ```

**GitHub PRs** (`prs/` folder):
- Queries for all open PRs authored by you
- Creates notes like `prs/your-repo-42.md`, `prs/your-other-repo-7.md`
- Each note has frontmatter properties:
  ```yaml
  ---
  number: 42
  title: "Enable nodepool autoscaling min zero"
  repo: "your-org/your-repo"
  repo_name: "your-repo"
  repo_owner: "your-org"
  url: "https://github.com/your-org/your-repo/pull/42"
  created: "2025-10-09"
  updated: "2025-12-11"
  draft: false
  category: "work"
  has_unanswered_comments: true
  ci_failed: false
  ci_pending: false
  ci_total_checks: 12
  source: "github"
  ---
  ```
- Each PR note includes visual indicators for:
  - 💬 Unanswered comments (last comment is from someone else)
  - ❌ Failed CI checks
  - ⏳ Pending CI checks

### Step 3: Use Obsidian Bases to View

After syncing, you can:

1. **Create a Base for JIRA issues**:
   - Open the `jira/` folder
   - Click "Create Base"
   - Filter/group by: status, priority, project, relationship
   - Sort by: updated date, priority, etc.

2. **Create a Base for PRs**:
   - Open the `prs/` folder
   - Click "Create Base"
   - Filter/group by: category, repo, draft status
   - Sort by: updated date, created date

3. **Create custom queries** in your daily note using Dataview:
   ```dataview
   TABLE status, priority, updated
   FROM "jira"
   WHERE relationship = "assigned"
   SORT updated DESC
   ```

4. **Find PRs needing attention** using Bases filters:
   - Filter by `has_unanswered_comments = true` to find PRs with pending responses
   - Filter by `ci_failed = true` to find PRs with failing tests
   - Filter by `category = "work"` to focus on work PRs vs documentation
   - Group by `repo_name` to see PRs by repository

## JIRA Query Coverage

The script searches across a configurable list of JIRA projects. Edit the `projects` list in `scripts/sync_daily_work.py` to match your organization's project keys. The script queries for issues where you are assigned, reporter, watcher, or commenter.

The script queries for issues where you are:

- **Assigned**: `assignee = currentUser()`
- **Reporter**: `reporter = currentUser()`
- **Watcher**: `watcher = currentUser()`
- **Commenter**: `issueFunction in commented("by currentUser()")`

All queries filter for open statuses: New, In Progress, Refinement, Backlog, Review, To Do

## GitHub PR Query Coverage

The script queries for:

- All open PRs authored by `@me`
- Automatically categorizes as: `work`, `documentation`, or `personal`
- Includes draft status for each PR

## Properties Reference

### JIRA Issue Properties

| Property | Type | Description |
|----------|------|-------------|
| `key` | text | Issue key (e.g., "PROJ-123") |
| `summary` | text | Issue title/summary |
| `type` | text | Issue type (Story, Epic, Bug, etc.) |
| `status` | text | Current status |
| `priority` | text | Priority level |
| `project` | text | Project key (e.g., "PROJ") |
| `assignee` | text | Assigned person |
| `reporter` | text | Person who created it |
| `created` | date | Creation date (YYYY-MM-DD) |
| `updated` | date | Last update date (YYYY-MM-DD) |
| `url` | text | Link to JIRA issue |
| `relationship` | text | Your relationship (assigned/reported/watching/commented) |
| `source` | text | Always "jira" |

### GitHub PR Properties

| Property | Type | Description |
|----------|------|-------------|
| `number` | number | PR number |
| `title` | text | PR title |
| `repo` | text | Full repo name (owner/name) |
| `repo_name` | text | Repository name only |
| `repo_owner` | text | Repository owner |
| `url` | text | Link to GitHub PR |
| `created` | date | Creation date (YYYY-MM-DD) |
| `updated` | date | Last update date (YYYY-MM-DD) |
| `draft` | boolean | Whether PR is a draft |
| `category` | text | work/documentation/personal |
| `has_unanswered_comments` | boolean | Last comment is from someone else |
| `ci_failed` | boolean | Any CI checks have failed |
| `ci_pending` | boolean | Any CI checks are pending |
| `ci_total_checks` | number | Total number of CI checks |
| `source` | text | Always "github" |

## Cleanup Behavior

The script automatically removes notes for:
- Closed JIRA issues (no longer in open statuses)
- Closed or merged GitHub PRs (no longer open)
- Issues/PRs that no longer match the queries

This keeps your vault clean and current.

## Example Workflow

1. User says: "Update my work tracking"

2. Run the sync script:
   ```bash
   uv run $VAULT_DIR/.claude/skills/daily-work-sync/scripts/sync_daily_work.py $VAULT_DIR
   ```

3. Script output:
   ```
   Querying JIRA issues...
   Querying GitHub PRs...

   Creating JIRA issue notes...
      ✓ PROJ-123
      ✓ PROJ-456
      ✓ PROJ-789
      ... (7 more)

   Creating GitHub PR notes...
      ✓ your-repo#42
      ✓ your-repo#57
      ... (8 more)

   Cleaning up closed items...
      Removed closed/stale: PROJ-99.md

   ✅ Sync complete!
      - 10 JIRA issues in $VAULT_DIR/jira
      - 10 GitHub PRs in $VAULT_DIR/prs

   💡 Use Obsidian Bases to view and filter these notes!
   ```

4. Tell the user what was created and suggest using Bases to explore the data.

## Requirements

- **jira-cli**: Must be installed and authenticated
- **gh CLI**: Must be installed and authenticated
- **Python 3**: For running the sync script
- **Obsidian Bases**: For optimal viewing (free core plugin)

## Troubleshooting

**No JIRA issues found**: Check that jira-cli is authenticated:
```bash
jira issue list -q "assignee = currentUser()" --limit 1
```

**No GitHub PRs found**: Check that gh CLI is authenticated:
```bash
gh auth status
```

**Script errors**: Run the script with `uv run` to see full error output:
```bash
uv run scripts/sync_daily_work.py /path/to/vault
```
