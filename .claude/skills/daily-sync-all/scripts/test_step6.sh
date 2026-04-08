#!/bin/bash
# Test Step 6 (project-tracker agent via SDK runner) with launchd-like env.
# Run this in a separate terminal (NOT inside a Claude Code session).
# Output is human-readable (timing printed to stderr by run_agent.py).
#
# Required env vars (set in your shell or a local .env before running):
#   VAULT_DIR                        - path to vault (default: auto-detected)
#   JIRA_API_TOKEN                   - your JIRA API token
#   ANTHROPIC_VERTEX_PROJECT_ID      - GCP project for Vertex AI (or unset to use Anthropic API)
#   GOOGLE_APPLICATION_CREDENTIALS   - path to GCP credentials JSON (Vertex only)
#
# Example:
#   export JIRA_API_TOKEN=your-token-here
#   export ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project
#   bash test_step6.sh

VAULT_DIR="${VAULT_DIR:-$(cd "$(dirname "$0")/../../../.." && pwd)}"

cd "$VAULT_DIR" || exit 1

exec env \
  PATH="$HOME/.local/bin:$(go env GOPATH 2>/dev/null)/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" \
  JIRA_API_TOKEN="${JIRA_API_TOKEN:?JIRA_API_TOKEN is required}" \
  CLAUDE_CODE_USE_VERTEX="${CLAUDE_CODE_USE_VERTEX:-}" \
  ANTHROPIC_VERTEX_PROJECT_ID="${ANTHROPIC_VERTEX_PROJECT_ID:-}" \
  GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-}" \
  ANTHROPIC_DEFAULT_SONNET_MODEL="${ANTHROPIC_DEFAULT_SONNET_MODEL:-claude-sonnet-4-6}" \
  uv run \
    "$VAULT_DIR/.claude/skills/daily-sync-all/scripts/run_agent.py" \
    project-tracker \
    "Run the project tracker agent for today's daily note." \
    2>&1
