---
name: people-dossier
description: |
  Build or refresh a People dossier by compiling past communications (Slack,
  Gmail, Meetings, JIRA) and synthesizing role, organization, and current
  projects into the ## Dossier section of each person's People page.
triggers:
  - /people-dossier
  - build dossier
  - dossier for
  - refresh dossier
  - update dossier
---

# People Dossier Skill

Builds or refreshes `## Dossier` sections on People pages by compiling past
communications and synthesizing role, organization, and current projects.

## Usage

| Command | What it does |
|---------|-------------|
| `/people-dossier` | Refresh dossiers for today's meeting attendees + Slack DMs |
| `/people-dossier Alex Chen` | Refresh dossier for a specific person |
| `/people-dossier --batch` | Refresh all people with activity in the last 30 days |

## Skill Steps

### 1. Parse the Request

Determine the target from the user's invocation:
- If a person's name is provided after the command → single-person mode
- If `--batch` is specified → batch mode
- Otherwise → daily mode (today's attendees + DM partners)

### 2. Run the Data Extractor

```bash
VAULT_DIR="${VAULT_DIR:-$(pwd)}"
DOSSIER_EXTRACT="$VAULT_DIR/.claude/skills/people-dossier/scripts/build_dossier.py"

# Daily mode (default):
uv run "$DOSSIER_EXTRACT" "$VAULT_DIR" --mode daily 2>&1 | tail -1

# Single person:
uv run "$DOSSIER_EXTRACT" "$VAULT_DIR" --person "Alex Chen" 2>&1 | tail -1

# Batch (all recent contacts):
uv run "$DOSSIER_EXTRACT" "$VAULT_DIR" --mode batch 2>&1 | tail -1
```

The last line of stdout is the path to the staging JSON file.
Capture this path for the next step.

Progress and diagnostics are printed to stderr — show them to the user.

### 3. Run the Dossier Synthesizer Agent

Use `run_agent.py` to invoke the `dossier-synthesizer` agent with the JSON path:

```bash
cd "$VAULT_DIR"
uv run .claude/skills/daily-sync-all/scripts/run_agent.py \
    dossier-synthesizer \
    "Synthesize people dossiers from <json_path>"
```

### 4. Report Back

Tell the user which People pages were updated, and whether any people were
skipped (not found in FastRover, page not found, etc.).

## Notes

- The data extractor (`build_dossier.py`) uses Slack, Gmail (pkm-sync search),
  Meetings, JIRA, and daily notes as sources
- FastRover provides official title, manager, and location (may be stale if
  cache is >30 days old)
- The synthesizer uses an LLM to interpret raw evidence and produce natural-language
  dossier sections — it does not just copy raw messages verbatim
- Dossiers are idempotent: re-running replaces the `## Dossier` section cleanly
  without touching hand-written notes above it
- Legacy People pages (no frontmatter) are supported; the dossier is appended at
  the end and does not modify existing hand-written content
