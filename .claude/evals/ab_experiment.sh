#!/bin/bash
# =============================================================================
# A/B Experiment Runner: Compare LLM providers on the daily sync pipeline
#
# Creates an isolated copy of the vault, runs LLM-powered agent steps
# against both the original (control) and clone (experiment), then diffs
# the generated markdown output.
#
# Usage:
#   ./ab_experiment.sh [--control-provider anthropic] [--experiment-provider ollama]
#                      [--steps 6,7,7.5,8] [--skip-control] [--skip-clone]
#                      [--experiment-dir /path/to/dir]
#
# The control run uses today's existing daily note output by default.
# Pass --run-control to re-run the control instead.
#
# Prerequisites:
#   - Steps 1-5 of sync_all_sources.sh have already run (data sync, calendar,
#     JIRA/PRs, vector index). These are LLM-free and produce the same data
#     regardless of provider.
#   - For Ollama experiments: Ollama running locally with the target model pulled
#   - Staging JSON files exist (conversations, dossier)
# =============================================================================

set -euo pipefail

# --- Configuration -----------------------------------------------------------

_find_vault_root() {
    local dir
    dir="$(cd "$(dirname "$0")" && pwd)"
    while [ "$dir" != "/" ]; do
        [ -d "$dir/.obsidian" ] && echo "$dir" && return
        dir="$(dirname "$dir")"
    done
    echo "ERROR: Could not find vault root" >&2; exit 1
}
VAULT_DIR="${VAULT_DIR:-$(_find_vault_root)}"
EXPERIMENT_BASE="${EXPERIMENT_BASE:-$HOME/.local/share/vault-experiments}"
CONTROL_PROVIDER="${CONTROL_PROVIDER:-anthropic}"
EXPERIMENT_PROVIDER="${EXPERIMENT_PROVIDER:-ollama}"
STEPS_CSV="${STEPS_CSV:-6,7,7.5,8}"
SKIP_CONTROL=false
SKIP_CLONE=false
RUN_CONTROL=false

# Ollama defaults
export OLLAMA_MODEL="${OLLAMA_MODEL:-gemma4:26b}"
export OLLAMA_NUM_CTX="${OLLAMA_NUM_CTX:-32768}"
export OLLAMA_MAX_TOKENS="${OLLAMA_MAX_TOKENS:-16384}"

# Disable obsidian CLI for clone runs — it talks to the original vault's Obsidian instance
# Agents fall back to Glob/Grep/Read which respect VAULT_DIR
export DISABLE_OBSIDIAN_CLI=1

# --- Parse Arguments ---------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --control-provider)   CONTROL_PROVIDER="$2"; shift 2;;
        --experiment-provider) EXPERIMENT_PROVIDER="$2"; shift 2;;
        --steps)              STEPS_CSV="$2"; shift 2;;
        --skip-control)       SKIP_CONTROL=true; shift;;
        --skip-clone)         SKIP_CLONE=true; shift;;
        --run-control)        RUN_CONTROL=true; shift;;
        --experiment-dir)     EXPERIMENT_BASE="$2"; shift 2;;
        --help|-h)
            sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
            exit 0;;
        *) echo "Unknown option: $1"; exit 1;;
    esac
done

# --- Helpers -----------------------------------------------------------------

_find_uv() {
    if command -v uv &>/dev/null; then command -v uv
    elif [ -x "$HOME/.local/bin/uv" ]; then echo "$HOME/.local/bin/uv"
    elif [ -x "/opt/homebrew/bin/uv" ]; then echo "/opt/homebrew/bin/uv"
    elif [ -x "/usr/local/bin/uv" ]; then echo "/usr/local/bin/uv"
    else echo "uv"; fi
}
UV="$(_find_uv)"

TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
EXPERIMENT_DIR="$EXPERIMENT_BASE/$TIMESTAMP"
CLONE_DIR="$EXPERIMENT_DIR/vault-clone"
REPORT_DIR="$EXPERIMENT_DIR/report"
LOG_DIR="$EXPERIMENT_DIR/logs"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
step() { echo ""; echo "[$(date '+%H:%M:%S')] === $* ==="; }

# Today's date components (for finding output files)
TODAY=$(date '+%Y-%m-%d')
YEAR=$(date '+%Y')
MONTH_DIR=$(date '+%m-%B')
DAY_DIR=$(date '+%d-%A')
DAY_NAME=$(date '+%A')
DAILY_NOTE_REL="daily/$YEAR/$MONTH_DIR/$TODAY-$DAY_NAME.md"

# --- Step 1: Create Experiment Directory -------------------------------------

step "Setting up experiment: $TIMESTAMP"
mkdir -p "$EXPERIMENT_DIR" "$REPORT_DIR" "$LOG_DIR"

log "Control provider:    $CONTROL_PROVIDER"
log "Experiment provider: $EXPERIMENT_PROVIDER"
log "Steps to run:        $STEPS_CSV"
log "Experiment dir:      $EXPERIMENT_DIR"
log "Daily note:          $DAILY_NOTE_REL"

# --- Step 2: Clone the Vault -------------------------------------------------

if [ "$SKIP_CLONE" = false ]; then
    step "Cloning vault to $CLONE_DIR"

    # rsync the full vault, excluding .git internals and caches
    # We need ALL content files (daily/, Meetings/, Projects/, People/, etc.)
    # plus the scripts and agents (.claude/) and .obsidian/ (for _find_vault_root)
    rsync -a \
        --exclude='.git/' \
        --exclude='__pycache__/' \
        --exclude='.DS_Store' \
        --exclude='*.pyc' \
        "$VAULT_DIR/" "$CLONE_DIR/"

    log "Clone complete: $(du -sh "$CLONE_DIR" | cut -f1)"
else
    log "Skipping clone (--skip-clone)"
    if [ ! -d "$CLONE_DIR" ]; then
        echo "ERROR: Clone directory does not exist: $CLONE_DIR" >&2
        exit 1
    fi
fi

# --- Step 3: Snapshot "Before" State -----------------------------------------

step "Snapshotting pre-experiment state"

# Capture the files that agents will modify
snapshot_files() {
    local base_dir="$1"
    local snapshot_dir="$2"
    mkdir -p "$snapshot_dir"

    # Daily note
    if [ -f "$base_dir/$DAILY_NOTE_REL" ]; then
        mkdir -p "$(dirname "$snapshot_dir/$DAILY_NOTE_REL")"
        cp "$base_dir/$DAILY_NOTE_REL" "$snapshot_dir/$DAILY_NOTE_REL"
    fi

    # Project notes (Work)
    if [ -d "$base_dir/Projects/Work" ]; then
        mkdir -p "$snapshot_dir/Projects/Work"
        cp "$base_dir/Projects/Work/"*.md "$snapshot_dir/Projects/Work/" 2>/dev/null || true
    fi

    # People pages
    if [ -d "$base_dir/People" ]; then
        mkdir -p "$snapshot_dir/People"
        cp "$base_dir/People/"*.md "$snapshot_dir/People/" 2>/dev/null || true
    fi
}

snapshot_files "$VAULT_DIR" "$EXPERIMENT_DIR/before-control"
snapshot_files "$CLONE_DIR" "$EXPERIMENT_DIR/before-experiment"

# --- Step 4: Run Agent Steps -------------------------------------------------

# Parse steps into array
IFS=',' read -ra STEPS <<< "$STEPS_CSV"

run_agent_step() {
    local provider="$1"
    local vault="$2"
    local step_num="$3"
    local log_prefix="$4"
    local agent_runner="$vault/.claude/skills/daily-sync-all/scripts/run_agent.py"

    export VAULT_DIR="$vault"
    export AGENT_PROVIDER="$provider"

    local start_time
    start_time=$(date +%s)

    case "$step_num" in
        6)
            log "[$log_prefix] Step 6: project-tracker ($provider)"
            (cd "$vault" && "$UV" run "$agent_runner" \
                project-tracker \
                "Run the project tracker agent for today's daily note." \
                2>&1) | tee "$LOG_DIR/${log_prefix}-step6.log"
            ;;
        7)
            log "[$log_prefix] Step 7: daily-curator ($provider)"
            (cd "$vault" && "$UV" run "$agent_runner" \
                daily-curator \
                "Curate today's daily note: write the Digest and Action Items sections." \
                2>&1) | tee "$LOG_DIR/${log_prefix}-step7.log"
            ;;
        7.5)
            log "[$log_prefix] Step 7.5: dossier-synthesizer ($provider)"
            # Find the most recent dossier staging JSON
            local dossier_json
            dossier_json=$(ls -t "$vault/.claude/skills/people-dossier/staging/dossier-daily-"*.json 2>/dev/null | head -1)
            if [ -z "$dossier_json" ]; then
                # Fall back to the main staging dir
                dossier_json=$(ls -t "$vault/.claude/skills/daily-sync-all/staging/dossier-daily-"*.json 2>/dev/null | head -1)
            fi
            if [ -n "$dossier_json" ] && [ -f "$dossier_json" ]; then
                (cd "$vault" && "$UV" run "$agent_runner" \
                    dossier-synthesizer \
                    "Synthesize people dossiers from $dossier_json" \
                    2>&1) | tee "$LOG_DIR/${log_prefix}-step7.5.log"
            else
                log "[$log_prefix] Step 7.5: No dossier JSON found, skipping"
            fi
            ;;
        8)
            log "[$log_prefix] Step 8: conversation-summarizer ($provider)"
            local conv_json
            conv_json=$(ls -t "$vault/.claude/skills/daily-sync-all/staging/conversations-"*.json 2>/dev/null | head -1)
            if [ -n "$conv_json" ] && [ -f "$conv_json" ]; then
                (cd "$vault" && "$UV" run "$agent_runner" \
                    conversation-summarizer \
                    "Summarize conversations from $conv_json into today's daily note." \
                    2>&1) | tee "$LOG_DIR/${log_prefix}-step8.log"
            else
                log "[$log_prefix] Step 8: No conversation JSON found, skipping"
            fi
            ;;
        *)
            log "[$log_prefix] Unknown step: $step_num, skipping"
            ;;
    esac

    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    echo "$step_num,$duration" >> "$LOG_DIR/${log_prefix}-timings.csv"
    log "[$log_prefix] Step $step_num completed in ${duration}s"
}

# --- Run Control (original vault, default provider) ---

if [ "$SKIP_CONTROL" = false ] && [ "$RUN_CONTROL" = true ]; then
    step "Running CONTROL ($CONTROL_PROVIDER) on original vault"
    for s in "${STEPS[@]}"; do
        run_agent_step "$CONTROL_PROVIDER" "$VAULT_DIR" "$s" "control"
    done
elif [ "$SKIP_CONTROL" = false ]; then
    step "Using existing daily note output as CONTROL baseline"
    log "(pass --run-control to re-run the control pipeline)"
fi

# Snapshot control "after" state
snapshot_files "$VAULT_DIR" "$EXPERIMENT_DIR/after-control"

# --- Run Experiment (cloned vault, experiment provider) ---

step "Running EXPERIMENT ($EXPERIMENT_PROVIDER) on cloned vault"
for s in "${STEPS[@]}"; do
    run_agent_step "$EXPERIMENT_PROVIDER" "$CLONE_DIR" "$s" "experiment"
done

# Snapshot experiment "after" state
snapshot_files "$CLONE_DIR" "$EXPERIMENT_DIR/after-experiment"

# --- Step 5: Diff and Report -------------------------------------------------

step "Generating comparison report"

diff_section() {
    local file_rel="$1"
    local label="$2"
    local control_file="$EXPERIMENT_DIR/after-control/$file_rel"
    local experiment_file="$EXPERIMENT_DIR/after-experiment/$file_rel"

    echo "### $label"
    echo ""

    if [ ! -f "$control_file" ] && [ ! -f "$experiment_file" ]; then
        echo "*Neither control nor experiment produced this file.*"
        echo ""
        return
    fi
    if [ ! -f "$control_file" ]; then
        echo "*Control file missing; experiment produced output.*"
        echo ""
        return
    fi
    if [ ! -f "$experiment_file" ]; then
        echo "*Experiment file missing; control produced output.*"
        echo ""
        return
    fi

    if diff -q "$control_file" "$experiment_file" >/dev/null 2>&1; then
        echo "*Identical output.*"
    else
        echo '```diff'
        diff -u "$control_file" "$experiment_file" \
            --label "control ($CONTROL_PROVIDER)" \
            --label "experiment ($EXPERIMENT_PROVIDER)" \
            | head -200
        echo '```'
    fi
    echo ""
}

# Build report
{
    echo "# A/B Experiment Report"
    echo ""
    echo "**Date:** $TODAY"
    echo "**Timestamp:** $TIMESTAMP"
    echo "**Control:** $CONTROL_PROVIDER"
    echo "**Experiment:** $EXPERIMENT_PROVIDER"
    echo "**Steps run:** $STEPS_CSV"
    echo ""

    # Timing comparison
    echo "## Performance"
    echo ""
    echo "| Step | Control (s) | Experiment (s) | Delta |"
    echo "|------|------------|----------------|-------|"
    for s in "${STEPS[@]}"; do
        control_time=$(grep "^$s," "$LOG_DIR/control-timings.csv" 2>/dev/null | cut -d, -f2 || echo "n/a")
        experiment_time=$(grep "^$s," "$LOG_DIR/experiment-timings.csv" 2>/dev/null | cut -d, -f2 || echo "n/a")
        if [ "$control_time" != "n/a" ] && [ "$experiment_time" != "n/a" ]; then
            delta=$((experiment_time - control_time))
            echo "| $s | $control_time | $experiment_time | ${delta}s |"
        else
            echo "| $s | ${control_time:-n/a} | ${experiment_time:-n/a} | - |"
        fi
    done
    echo ""

    # File diffs
    echo "## Output Comparison"
    echo ""

    # Daily note
    diff_section "$DAILY_NOTE_REL" "Daily Note ($DAILY_NOTE_REL)"

    # Project notes
    if [ -d "$EXPERIMENT_DIR/after-control/Projects/Work" ]; then
        for f in "$EXPERIMENT_DIR/after-control/Projects/Work/"*.md; do
            [ -f "$f" ] || continue
            rel="Projects/Work/$(basename "$f")"
            diff_section "$rel" "$(basename "$f")"
        done
    fi

    # People pages (only show ones that changed)
    if [ -d "$EXPERIMENT_DIR/after-control/People" ]; then
        changed_count=0
        for f in "$EXPERIMENT_DIR/after-control/People/"*.md; do
            [ -f "$f" ] || continue
            rel="People/$(basename "$f")"
            exp_f="$EXPERIMENT_DIR/after-experiment/$rel"
            if [ -f "$exp_f" ] && ! diff -q "$f" "$exp_f" >/dev/null 2>&1; then
                diff_section "$rel" "People/$(basename "$f")"
                changed_count=$((changed_count + 1))
            fi
        done
        if [ "$changed_count" -eq 0 ]; then
            echo "### People Pages"
            echo ""
            echo "*No differences in People pages.*"
            echo ""
        fi
    fi

    # Structural checks
    echo "## Structural Checks"
    echo ""

    check_sections() {
        local file="$1"
        local label="$2"
        echo "**$label:**"
        if [ ! -f "$file" ]; then
            echo "- File not found"
            return
        fi
        for section in "### Meeting Prep" "### Digest" "### Action Items" "### Active Projects" "### Upcoming Deadlines" "### Conversations"; do
            if grep -q "^$section" "$file" 2>/dev/null; then
                echo "- $section: PRESENT"
            else
                echo "- $section: MISSING"
            fi
        done
    }

    check_sections "$EXPERIMENT_DIR/after-control/$DAILY_NOTE_REL" "Control daily note"
    echo ""
    check_sections "$EXPERIMENT_DIR/after-experiment/$DAILY_NOTE_REL" "Experiment daily note"
    echo ""

    # Wiki-link validation
    echo "## Wiki-Link Validation"
    echo ""
    for variant in "after-control" "after-experiment"; do
        label=$(echo "$variant" | sed 's/after-//')
        file="$EXPERIMENT_DIR/$variant/$DAILY_NOTE_REL"
        if [ -f "$file" ]; then
            # Count wiki-links
            total_links=$(grep -oE '\[\[[^]]+\]\]' "$file" | wc -l | tr -d ' ')
            # Check for unescaped pipes in tables (lines starting with |)
            bad_pipes=$(grep '^|' "$file" | grep -oE '\[\[[^]]*[^\\]\|[^]]*\]\]' | wc -l | tr -d ' ')
            echo "**$label:** $total_links wiki-links, $bad_pipes unescaped pipes in tables"
        fi
    done
    echo ""

    echo "## Logs"
    echo ""
    echo "Full logs available in: \`$LOG_DIR/\`"
    echo ""
    for f in "$LOG_DIR/"*.log; do
        [ -f "$f" ] || continue
        echo "- \`$(basename "$f")\` ($(wc -l < "$f" | tr -d ' ') lines)"
    done

} > "$REPORT_DIR/comparison-$TIMESTAMP.md"

step "Experiment complete"
log "Report: $REPORT_DIR/comparison-$TIMESTAMP.md"
log "Logs:   $LOG_DIR/"
log "Control output:    $EXPERIMENT_DIR/after-control/"
log "Experiment output: $EXPERIMENT_DIR/after-experiment/"
echo ""
echo "To review: cat $REPORT_DIR/comparison-$TIMESTAMP.md"
