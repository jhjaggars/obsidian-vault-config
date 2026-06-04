#!/bin/bash
# Parallel dossier synthesizer runner.
#
# Splits the full dossier JSON into chunks and runs multiple dossier-synthesizer
# agent instances in parallel, skipping people who already have a ## Dossier section.
#
# Usage:
#   bash run_batch_dossier.sh <dossier-json-path> [parallelism] [chunk-size]
#
# Defaults: parallelism=6, chunk-size=15

set -u

DOSSIER_JSON="${1:?Usage: $0 <dossier-json-path> [parallelism] [chunk-size]}"
PARALLELISM="${2:-6}"
CHUNK_SIZE="${3:-15}"

_find_vault_root() {
    local dir
    dir="$(cd "$(dirname "$0")" && pwd)"
    while [ "$dir" != "/" ]; do
        [ -d "$dir/.obsidian" ] && echo "$dir" && return
        dir="$(dirname "$dir")"
    done
    echo "ERROR: Could not find vault root" >&2
    exit 1
}
VAULT_DIR="${VAULT_DIR:-$(_find_vault_root)}"

_find_uv() {
    if command -v uv &>/dev/null; then command -v uv
    elif [ -x "$HOME/.local/bin/uv" ]; then echo "$HOME/.local/bin/uv"
    elif [ -x "/opt/homebrew/bin/uv" ]; then echo "/opt/homebrew/bin/uv"
    else echo "uv"; fi
}
UV="${UV:-$(_find_uv)}"

AGENT_RUNNER="$VAULT_DIR/.claude/skills/daily-sync-all/scripts/run_agent.py"
STAGING_DIR="$VAULT_DIR/.claude/skills/people-dossier/staging"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# Build filtered JSON: exclude people who already have ## Dossier written
FILTERED_JSON="$STAGING_DIR/dossier-filtered.json"
log "Filtering out already-completed people..."
python3 - "$DOSSIER_JSON" "$VAULT_DIR" "$FILTERED_JSON" << 'PYEOF'
import json, sys
from pathlib import Path

source_path, vault_dir, out_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
d = json.load(open(source_path))

remaining = []
skipped = 0
for person in d["people"]:
    page = vault_dir / person["page_path"]
    if page.exists():
        content = page.read_text(encoding="utf-8", errors="replace")
        if "## Dossier" in content:
            skipped += 1
            continue
    remaining.append(person)

out = {**d, "people": remaining}
json.dump(out, open(out_path, "w"), indent=2, default=str)
print(f"Skipped {skipped} already done. {len(remaining)} remaining.", file=sys.stderr)
PYEOF

REMAINING=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(len(d['people']))" "$FILTERED_JSON")
log "Processing $REMAINING people with parallelism=$PARALLELISM, chunk-size=$CHUNK_SIZE"

if [ "$REMAINING" -eq 0 ]; then
    log "All people already have dossiers — nothing to do."
    rm -f "$FILTERED_JSON"
    exit 0
fi

# Split into chunk files
TOTAL_CHUNKS=$(python3 -c "import math,sys; print(math.ceil(int(sys.argv[1])/int(sys.argv[2])))" "$REMAINING" "$CHUNK_SIZE")
log "Creating $TOTAL_CHUNKS chunks..."

python3 - "$FILTERED_JSON" "$STAGING_DIR" "$CHUNK_SIZE" << 'PYEOF'
import json, sys, math
from pathlib import Path

source_path, staging_dir, chunk_size = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
d = json.load(open(source_path))
people = d["people"]
meta = {k: v for k, v in d.items() if k != "people"}

# Remove any old chunk files
for f in staging_dir.glob("dossier-chunk-*.json"):
    f.unlink()

n_chunks = math.ceil(len(people) / chunk_size)
for i in range(n_chunks):
    chunk_people = people[i * chunk_size:(i + 1) * chunk_size]
    chunk = {**meta, "people": chunk_people}
    out_path = staging_dir / f"dossier-chunk-{i+1:03d}.json"
    json.dump(chunk, open(out_path, "w"), indent=2, default=str)

print(f"Created {n_chunks} chunk files in {staging_dir}", file=sys.stderr)
PYEOF

# Run agents in parallel with a concurrency cap
CHUNK_FILES=("$STAGING_DIR"/dossier-chunk-*.json)
TOTAL="${#CHUNK_FILES[@]}"
log "Running $TOTAL chunks with up to $PARALLELISM agents in parallel..."

COMPLETED=0
FAILED=0

run_chunk() {
    local chunk_file="$1"
    local chunk_num="$2"
    local result
    (cd "$VAULT_DIR" && "$UV" run "$AGENT_RUNNER" \
        dossier-synthesizer \
        "Synthesize people dossiers from $chunk_file" \
        2>&1) && result=0 || result=1

    rm -f "$chunk_file"
    return $result
}

# Process chunks with parallelism cap using job slots
declare -a PIDS=()
CHUNK_IDX=0

while [ "$CHUNK_IDX" -lt "$TOTAL" ]; do
    # Fill up to PARALLELISM parallel jobs
    while [ "${#PIDS[@]}" -lt "$PARALLELISM" ] && [ "$CHUNK_IDX" -lt "$TOTAL" ]; do
        CHUNK_FILE="${CHUNK_FILES[$CHUNK_IDX]}"
        CHUNK_NUM=$((CHUNK_IDX + 1))
        log "Starting chunk $CHUNK_NUM/$TOTAL: $(basename "$CHUNK_FILE")"
        run_chunk "$CHUNK_FILE" "$CHUNK_NUM" &
        PIDS+=($!)
        CHUNK_IDX=$((CHUNK_IDX + 1))
    done

    # Wait for one job to finish before starting more
    WAIT_PID="${PIDS[0]}"
    PIDS=("${PIDS[@]:1}")  # shift first element
    if wait "$WAIT_PID"; then
        COMPLETED=$((COMPLETED + 1))
    else
        FAILED=$((FAILED + 1))
    fi
    log "Progress: $COMPLETED completed, $FAILED failed, $((CHUNK_IDX - ${#PIDS[@]} - COMPLETED - FAILED)) in flight"
done

# Wait for remaining in-flight jobs
for PID in "${PIDS[@]}"; do
    if wait "$PID"; then
        COMPLETED=$((COMPLETED + 1))
    else
        FAILED=$((FAILED + 1))
    fi
done

# Cleanup
rm -f "$FILTERED_JSON"
for f in "$STAGING_DIR"/dossier-chunk-*.json; do rm -f "$f"; done

log "=== Batch complete: $COMPLETED/$TOTAL chunks succeeded, $FAILED failed ==="
log "People processed: ~$((COMPLETED * CHUNK_SIZE)) / $REMAINING"
