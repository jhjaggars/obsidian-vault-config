#!/usr/bin/env bash
# setup-launchagents.sh — Install/manage launchd agents for the vault sync pipeline.
#
# Usage: setup-launchagents.sh [install|uninstall|reinstall|status]
#
# Secrets are read from .claude/launchagents.env (gitignored) or from environment variables.
# See .claude/launchagents.env.example for required and optional variables.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_DIR="$(dirname "$SCRIPT_DIR")"
LAUNCHAGENTS_DIR="$HOME/Library/LaunchAgents"
ENV_FILE="$SCRIPT_DIR/launchagents.env"

# Load local env file if present
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    set -o allexport
    source "$ENV_FILE"
    set +o allexport
fi

# Defaults for non-secret variables (match current installed values; override via launchagents.env)
AGENT_PATH="${AGENT_PATH:-${HOME}/.local/bin:${HOME}/go/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin}"
CLAUDE_CODE_USE_VERTEX="${CLAUDE_CODE_USE_VERTEX:-1}"
ANTHROPIC_VERTEX_PROJECT_ID="${ANTHROPIC_VERTEX_PROJECT_ID:-itpc-gcp-hcm-pe-eng-claude}"
GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-${HOME}/.config/gcloud/application_default_credentials.json}"
ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-opusplan}"
ANTHROPIC_DEFAULT_SONNET_MODEL="${ANTHROPIC_DEFAULT_SONNET_MODEL:-claude-sonnet-4-6[1m]}"
ANTHROPIC_DEFAULT_OPUS_MODEL="${ANTHROPIC_DEFAULT_OPUS_MODEL:-claude-opus-4-6}"
ANTHROPIC_DEFAULT_HAIKU_MODEL="${ANTHROPIC_DEFAULT_HAIKU_MODEL:-claude-haiku-4-6}"

LABELS=(
    "com.user.daily-work-sync"
    "com.user.sync-watchdog"
    "com.user.weekly-gap-analysis"
)

plist_file() { echo "$LAUNCHAGENTS_DIR/$1.plist"; }
service_target() { echo "gui/$(id -u)/$1"; }

# ---------------------------------------------------------------------------
# Plist generators
# ---------------------------------------------------------------------------

generate_daily_work_sync() {
    cat > "$(plist_file com.user.daily-work-sync)" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.daily-work-sync</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${VAULT_DIR}/.claude/skills/daily-sync-all/scripts/sync_all_sources.sh</string>
    </array>

    <key>StartInterval</key>
    <integer>3600</integer>

    <key>WorkingDirectory</key>
    <string>${VAULT_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${AGENT_PATH}</string>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>JIRA_API_TOKEN</key>
        <string>${JIRA_API_TOKEN}</string>
        <key>CLAUDE_CODE_USE_VERTEX</key>
        <string>${CLAUDE_CODE_USE_VERTEX}</string>
        <key>ANTHROPIC_VERTEX_PROJECT_ID</key>
        <string>${ANTHROPIC_VERTEX_PROJECT_ID}</string>
        <key>GOOGLE_APPLICATION_CREDENTIALS</key>
        <string>${GOOGLE_APPLICATION_CREDENTIALS}</string>
        <key>ANTHROPIC_MODEL</key>
        <string>${ANTHROPIC_MODEL}</string>
        <key>ANTHROPIC_DEFAULT_SONNET_MODEL</key>
        <string>${ANTHROPIC_DEFAULT_SONNET_MODEL}</string>
        <key>ANTHROPIC_DEFAULT_OPUS_MODEL</key>
        <string>${ANTHROPIC_DEFAULT_OPUS_MODEL}</string>
        <key>ANTHROPIC_DEFAULT_HAIKU_MODEL</key>
        <string>${ANTHROPIC_DEFAULT_HAIKU_MODEL}</string>
    </dict>

    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/daily-work-sync/stdout.log</string>

    <key>StandardErrorPath</key>
    <string>${HOME}/Library/Logs/daily-work-sync/stderr.log</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
}

generate_sync_watchdog() {
    cat > "$(plist_file com.user.sync-watchdog)" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.sync-watchdog</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${VAULT_DIR}/.claude/skills/daily-sync-all/scripts/sync_watchdog.sh</string>
    </array>

    <key>StartInterval</key>
    <integer>1800</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>WorkingDirectory</key>
    <string>${VAULT_DIR}</string>

    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/daily-work-sync/watchdog.log</string>

    <key>StandardErrorPath</key>
    <string>${HOME}/Library/Logs/daily-work-sync/watchdog.log</string>
</dict>
</plist>
EOF
}

generate_weekly_gap_analysis() {
    cat > "$(plist_file com.user.weekly-gap-analysis)" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.weekly-gap-analysis</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${VAULT_DIR}/.claude/skills/weekly-gap-analysis/scripts/run_weekly_gap_analysis.sh</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>5</integer>
        <key>Hour</key>
        <integer>10</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>WorkingDirectory</key>
    <string>${VAULT_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${AGENT_PATH}</string>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>CLAUDE_CODE_USE_VERTEX</key>
        <string>${CLAUDE_CODE_USE_VERTEX}</string>
        <key>ANTHROPIC_VERTEX_PROJECT_ID</key>
        <string>${ANTHROPIC_VERTEX_PROJECT_ID}</string>
        <key>GOOGLE_APPLICATION_CREDENTIALS</key>
        <string>${GOOGLE_APPLICATION_CREDENTIALS}</string>
        <key>ANTHROPIC_DEFAULT_SONNET_MODEL</key>
        <string>${ANTHROPIC_DEFAULT_SONNET_MODEL}</string>
    </dict>

    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/weekly-gap-analysis/stdout.log</string>

    <key>StandardErrorPath</key>
    <string>${HOME}/Library/Logs/weekly-gap-analysis/stderr.log</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_status() {
    echo "=== LaunchAgent Status ==="
    local uid
    uid=$(id -u)
    for label in "${LABELS[@]}"; do
        local plist
        plist="$(plist_file "$label")"
        local plist_status loaded
        if [[ -f "$plist" ]]; then
            plist_status="plist exists"
        else
            plist_status="plist MISSING"
        fi
        if launchctl list "$label" &>/dev/null; then
            local exit_code last_pid
            exit_code=$(launchctl list "$label" | awk '/LastExitStatus/ {print $3}' | tr -d ';')
            last_pid=$(launchctl list "$label" | awk '/PID/ {print $3}' | tr -d ';')
            loaded="LOADED (pid=${last_pid:-none}, exit=${exit_code:-?})"
        else
            loaded="not loaded"
        fi
        printf "  %-40s  %s  [%s]\n" "$label" "$loaded" "$plist_status"
    done
}

cmd_install() {
    if [[ -z "${JIRA_API_TOKEN:-}" ]]; then
        echo "ERROR: JIRA_API_TOKEN is not set." >&2
        echo "  Set it in $ENV_FILE or export it as an environment variable." >&2
        echo "  See $SCRIPT_DIR/launchagents.env.example for details." >&2
        exit 1
    fi

    echo "Creating log directories..."
    mkdir -p "$HOME/Library/Logs/daily-work-sync"
    mkdir -p "$HOME/Library/Logs/weekly-gap-analysis"

    echo "Generating plists..."
    generate_daily_work_sync
    generate_sync_watchdog
    generate_weekly_gap_analysis

    echo "Loading agents..."
    local uid
    uid=$(id -u)
    for label in "${LABELS[@]}"; do
        local plist
        plist="$(plist_file "$label")"
        # Unload if already running (ignore errors)
        launchctl bootout "gui/${uid}/${label}" 2>/dev/null || true
        launchctl bootstrap "gui/${uid}" "$plist"
        echo "  Loaded: $label"
    done

    echo "Done. Run '$0 status' to verify."
}

cmd_uninstall() {
    local uid
    uid=$(id -u)
    for label in "${LABELS[@]}"; do
        local plist
        plist="$(plist_file "$label")"
        if launchctl bootout "gui/${uid}/${label}" 2>/dev/null; then
            echo "  Unloaded: $label"
        else
            echo "  Not loaded (skipping bootout): $label"
        fi
        if [[ -f "$plist" ]]; then
            rm "$plist"
            echo "  Removed: $plist"
        fi
    done
    echo "Done. Log directories left intact."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-install}" in
    install)   cmd_install ;;
    uninstall) cmd_uninstall ;;
    reinstall) cmd_uninstall; echo; cmd_install ;;
    status)    cmd_status ;;
    *)
        echo "Usage: $0 [install|uninstall|reinstall|status]" >&2
        exit 1
        ;;
esac
