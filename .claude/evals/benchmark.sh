#!/bin/bash
# benchmark.sh — Measure tok/s and memory for each Gemma 4 variant on this machine
# Usage: bash .claude/evals/benchmark.sh [--runs N]
#
# Sends a representative prompt (system prompt excerpt + tool-use scenario) to each model
# via Ollama's /api/chat endpoint. Parses eval_count / eval_duration for tok/s.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

RUNS=3
while [[ $# -gt 0 ]]; do
    case "$1" in
        --runs) RUNS="${2:-3}"; shift 2 ;;
        *) RUNS="$1"; shift ;;
    esac
done

MODELS=("gemma4:e4b" "gemma4:26b" "gemma4:31b")
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"

# Build a representative system prompt excerpt (first 200 lines of project-tracker, minus frontmatter)
SYSTEM_PROMPT=$(sed -n '/^---$/,/^---$/!p' "$VAULT_DIR/.claude/agents/project-tracker.md" | head -200)
USER_MSG="Read Work Pipeline.md and list all active projects from the Early and Mature columns. For each project, describe what data sources you would search and why."

echo "======================================"
echo "Gemma 4 Benchmark — $(date)"
echo "Machine: $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'unknown')"
echo "RAM: $(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f GB", $1/1073741824}')"
echo "Ollama: $(ollama --version 2>/dev/null || echo 'unknown')"
echo "Runs per model: $RUNS"
echo "======================================"
echo ""

SYSTEM_JSON=$(python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" <<< "$SYSTEM_PROMPT")
USER_JSON=$(python3 -c "import json,sys; print(json.dumps(sys.stdin.read()))" <<< "$USER_MSG")

for model in "${MODELS[@]}"; do
    echo "=== $model ==="

    # Ensure model is available
    if ! ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$model"; then
        echo "  SKIP: model not pulled (run: ollama pull $model)"
        echo ""
        continue
    fi

    # Warm up — load model into memory
    echo "  Warming up..."
    curl -s "$OLLAMA_URL/api/chat" -d "{
        \"model\": \"$model\",
        \"messages\": [{\"role\": \"user\", \"content\": \"hello\"}],
        \"stream\": false,
        \"options\": {\"num_predict\": 10}
    }" > /dev/null 2>&1

    total_toks=0
    total_prompt_toks=0
    total_wall_ms=0
    total_eval_toks_per_sec=0

    for run in $(seq 1 "$RUNS"); do
        START_NS=$(python3 -c "import time; print(int(time.time_ns()))")

        RESULT=$(curl -s "$OLLAMA_URL/api/chat" -d "{
            \"model\": \"$model\",
            \"messages\": [
                {\"role\": \"system\", \"content\": $SYSTEM_JSON},
                {\"role\": \"user\", \"content\": $USER_JSON}
            ],
            \"stream\": false,
            \"options\": {\"num_predict\": 2048, \"num_ctx\": 8192}
        }")

        END_NS=$(python3 -c "import time; print(int(time.time_ns()))")

        METRICS=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    eval_count = d.get('eval_count', 0)
    eval_dur = d.get('eval_duration', 1)  # nanoseconds
    prompt_eval = d.get('prompt_eval_count', 0)
    prompt_dur = d.get('prompt_eval_duration', 1)
    tps = eval_count / (eval_dur / 1e9) if eval_dur > 0 else 0
    prompt_tps = prompt_eval / (prompt_dur / 1e9) if prompt_dur > 0 else 0
    print(f'{eval_count} {prompt_eval} {tps:.1f} {prompt_tps:.1f}')
except Exception as e:
    print(f'0 0 0.0 0.0', file=sys.stderr)
    print('0 0 0.0 0.0')
" <<< "$RESULT")

        read eval_count prompt_eval tps prompt_tps <<< "$METRICS"
        wall_ms=$(( (END_NS - START_NS) / 1000000 ))

        echo "  Run $run: ${eval_count} output tok @ ${tps} tok/s | ${prompt_eval} prompt tok @ ${prompt_tps} tok/s | ${wall_ms}ms wall"

        total_toks=$((total_toks + eval_count))
        total_prompt_toks=$((total_prompt_toks + prompt_eval))
        total_wall_ms=$((total_wall_ms + wall_ms))
        total_eval_toks_per_sec=$(python3 -c "print(${total_eval_toks_per_sec} + ${tps})")
    done

    avg_tps=$(python3 -c "print(f'{${total_eval_toks_per_sec} / ${RUNS}:.1f}')")
    avg_wall=$(python3 -c "print(f'{${total_wall_ms} / ${RUNS}:.0f}')")
    avg_output=$(python3 -c "print(f'{${total_toks} / ${RUNS}:.0f}')")

    echo "  ---"
    echo "  Average: ${avg_tps} tok/s | ${avg_output} output tokens | ${avg_wall}ms wall"
    echo ""
done

echo "======================================"
echo "Memory usage (check Activity Monitor for Ollama process)"
echo "Done."
