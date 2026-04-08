#!/bin/bash
# Minimal claude -p test with same Vertex env as test_step6.sh.
# Run in a separate terminal (NOT inside a Claude Code session).
# Usage: bash test_simple.sh | python3 parse_stream.py
#
# Set ANTHROPIC_VERTEX_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS if using Vertex AI.
# Otherwise uses the Anthropic API directly.

VAULT_DIR="${VAULT_DIR:-$(cd "$(dirname "$0")/../../../.." && pwd)}"

cd "$VAULT_DIR" || exit 1

exec env \
  CLAUDECODE="" \
  PATH="$HOME/.local/bin:$(go env GOPATH 2>/dev/null)/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" \
  CLAUDE_CODE_USE_VERTEX="${CLAUDE_CODE_USE_VERTEX:-}" \
  ANTHROPIC_VERTEX_PROJECT_ID="${ANTHROPIC_VERTEX_PROJECT_ID:-}" \
  GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-}" \
  ANTHROPIC_DEFAULT_SONNET_MODEL="${ANTHROPIC_DEFAULT_SONNET_MODEL:-claude-sonnet-4-6[1m]}" \
  ANTHROPIC_DEFAULT_OPUS_MODEL="${ANTHROPIC_DEFAULT_OPUS_MODEL:-claude-opus-4-6}" \
  ANTHROPIC_DEFAULT_HAIKU_MODEL="${ANTHROPIC_DEFAULT_HAIKU_MODEL:-claude-haiku-4-6}" \
  claude -p \
    --permission-mode bypassPermissions \
    --verbose --output-format stream-json \
    "What is today's date? Answer in one sentence." \
    2>&1
