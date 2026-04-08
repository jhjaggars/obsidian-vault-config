---
name: youtube-process-recommendations
description: "Batch-process checked YouTube videos from a recommendations file. Finds all checked items without completion stamps, processes each through the youtube-transcript workflow, and updates the file with success/failure stamps. Triggers on: process youtube recommendations, process checked videos, analyze checked youtube, run youtube queue."
---

# YouTube Process Recommendations Skill

This skill automates batch processing of checked videos from a YouTube recommendations file. It finds all checked items that haven't been processed yet, runs the full transcript/analysis workflow for each, and stamps the results back into the recommendations file.

## Triggers

- "process youtube recommendations"
- "process checked videos"
- "analyze checked youtube"
- "run youtube queue"

## Workflow

### Step 1: Find Recommendations File

Look for the most recent recommendations file in the YouTube hierarchy.

If the user provides a specific path as an argument, use that file instead.

Otherwise, find the most recent recommendations file:

**With CLI** (preferred):
```bash
obsidian search query="file:recommendations" path="YouTube/" format=json
```
Pick the result with the most recent date prefix in the filename.

**Without CLI** (fallback):
Use Glob to find `YouTube/**/*-recommendations.md`, then sort by filename descending and take the first result.

If no recommendations file is found, tell the user and suggest running the `youtube-recommendations` skill first.

### Step 2: Parse Checked Items

Read the recommendations file and find all lines matching this pattern:
```
- [x] [Title](https://www.youtube.com/watch?v=VIDEO_ID) - Channel (duration) - *reason*
```

**Important**: SKIP lines that already contain a completion stamp:
- `[PROCESSED: YYYY-MM-DD]` (success stamp)
- `[FAILED: YYYY-MM-DD - reason]` (failure stamp)

Note: Obsidian may add its own timestamp when you check a box (like `✅ YYYY-MM-DD`). The skill ignores these and only looks for the `[PROCESSED:]` or `[FAILED:]` stamps.

Extract for each unchecked item:
- Video title (from link text)
- Video URL (from link href)
- Channel name (after the closing `] - ` and before the duration)
- Duration (in parentheses)
- Reason (in italics)

### Step 3: Report Queue

Before processing, tell the user:
- Path to the recommendations file being processed
- How many checked videos were found
- List of video titles to be processed

Ask the user to confirm before proceeding (unless they explicitly said "yes" or "go" in their initial request).

### Step 4: Process Each Video

For each video URL in the queue:

1. **Report progress**: "Processing video N of M: [Title]"

2. **Launch a sub-agent** using the Task tool with `subagent_type: general-purpose`. Each video gets its own isolated context window. Pass the full youtube-transcript workflow instructions and all necessary context in the prompt.

   The sub-agent prompt should include:
   - The video URL to process
   - The full contents of `.claude/skills/youtube-transcript/SKILL.md` (read it first)
   - The full contents of `.claude/skills/youtube-transcript/format_transcript.py` (read it first)
   - The absolute vault path (current working directory)
   - Today's date for frontmatter
   - Instruction to return a JSON result on the last line in this format:
     ```
     RESULT: {"status": "success", "transcript_note": "YouTube/...", "analysis_note": "YouTube/..."}
     ```
     or on failure:
     ```
     RESULT: {"status": "failure", "reason": "brief error description"}
     ```

   Example sub-agent prompt structure:
   ```
   Process this YouTube video and create transcript + analysis notes in the Obsidian vault at /path/to/vault.

   Video URL: https://www.youtube.com/watch?v=VIDEO_ID
   Today's date: YYYY-MM-DD

   Follow these instructions exactly:

   [Full contents of youtube-transcript/SKILL.md]

   The format_transcript.py script is at: /path/to/vault/.claude/skills/youtube-transcript/format_transcript.py

   After completing all steps (or if you encounter a fatal error), output your final result as the last line:
   RESULT: {"status": "success", "transcript_note": "YouTube/...", "analysis_note": "YouTube/..."}
   or
   RESULT: {"status": "failure", "reason": "..."}
   ```

3. **Parse sub-agent result**: Read the last `RESULT:` line from the sub-agent's response to determine success or failure.

4. **Handle success**: If the sub-agent reports success:
   - Find the line in the recommendations file for this video
   - Append ` [PROCESSED: YYYY-MM-DD]` to the end of the line (use today's date)
   - Write the updated file back

5. **Handle failure**: If the sub-agent reports failure or the Task tool itself errors:
   - Capture the error reason from the result or from the exception
   - Find the line in the recommendations file for this video
   - Append ` [FAILED: YYYY-MM-DD - reason]` to the end of the line
   - Write the updated file back
   - **Continue to next video** — don't halt the entire batch

6. **Track results**: Keep running counts of successes and failures

### Step 5: Report Summary

After processing all videos, report:
- Total videos processed
- Successes: N videos (list titles)
- Failures: N videos (list titles and error reasons)
- Paths to created transcript/analysis notes (for successes)
- Next steps: "Review the updated recommendations file at [path]"

## Implementation Notes

### Sub-Agent Strategy

Processing each video in its own sub-agent (`subagent_type: general-purpose`) isolates the context so long transcripts, web searches, and analysis from one video don't consume context that other videos need. The sub-agent has access to all tools (Bash, Write, WebSearch, Glob, Read, etc.) and runs the complete youtube-transcript workflow independently.

**Before launching sub-agents**, read these files once and embed their contents in each sub-agent prompt:
- `.claude/skills/youtube-transcript/SKILL.md` — the full processing instructions
- `.claude/skills/youtube-transcript/format_transcript.py` — the transcript formatter script path

**Sub-agents run sequentially** (not in parallel) to avoid file system conflicts when writing notes to the hierarchical `YouTube/` folder structure.

### Line Matching

Use a regex or careful string parsing to match lines like:
```
- [x] [Video Title](https://www.youtube.com/watch?v=VIDEO_ID) - Channel Name (HH:MM:SS) - *classification reason*
```

**Key patterns**:
- Starts with `- [x] `
- Contains `[Text](URL)` markdown link
- URL matches `youtube.com/watch?v=` or `youtu.be/`
- Followed by ` - Channel (duration) - *reason*`

**Completion stamps to skip**:
- Line contains `[PROCESSED: ` followed by a date and closing bracket
- Line contains `[FAILED: ` followed by a date, reason, and closing bracket

### Updating Lines

When updating a line with a stamp:
1. Read the entire file
2. Find the specific line by matching the video URL (most reliable identifier)
3. Append the stamp to the END of the line
4. Write the entire file back

Preserve all other content in the file unchanged.

### Error Handling

Common errors and their reasons:
- `youtube_transcript_api` fails → "transcript unavailable"
- `yt-dlp` fails → "metadata fetch failed"
- WebSearch fails → "verification failed" (but continue — the analysis note can still be created without verification)
- File write fails → "file write error"

If a video fails, log the error but continue to the next video. The batch should be resilient.

### Date Format

Use ISO format `YYYY-MM-DD` for all stamps (today's date when processing).

## Example Usage

```
User: "process youtube recommendations"

Claude:
I'll process checked videos from YouTube/2026/02-February/16-Sunday/2026-02-16-recommendations.md

Found 2 checked videos:
1. "The Devil Himself! - The Worst of The Epstein Files"
2. "State Of Agentic Coding #3 with Armin and Ben"

Processing video 1 of 2: The Devil Himself! - The Worst of The Epstein Files
✓ Fetched metadata
✓ Downloaded transcript
✓ Created transcript note: YouTube/2026/02-February/13-Thursday/2026-02-13-epstein-files.md
✓ Analyzed content and verified claims
✓ Created analysis note: YouTube/2026/02-February/13-Thursday/2026-02-13-epstein-files - Analysis.md
✓ Updated recommendations file with [PROCESSED: 2026-02-16] stamp

Processing video 2 of 2: State Of Agentic Coding #3 with Armin and Ben
✓ Fetched metadata
✓ Downloaded transcript
✓ Created transcript note: YouTube/2025/11-November/12-Wednesday/2025-11-12-state-of-agentic-coding-3.md
✓ Analyzed content and verified claims
✓ Created analysis note: YouTube/2025/11-November/12-Wednesday/2025-11-12-state-of-agentic-coding-3 - Analysis.md
✓ Updated recommendations file with [PROCESSED: 2026-02-16] stamp

Summary:
✓ 2 videos processed successfully
✗ 0 failures

All done! Review the updated file at YouTube/2026/02-February/16-Sunday/2026-02-16-recommendations.md
```

## Dependencies

- Task tool with `subagent_type: general-purpose` (one sub-agent per video)
- `.claude/skills/youtube-transcript/SKILL.md` (embedded in each sub-agent prompt)
- `.claude/skills/youtube-transcript/format_transcript.py` (used by sub-agents)
- `uvx yt-dlp` (for metadata, run inside sub-agents)
- `uvx youtube-transcript-api` (for transcripts, run inside sub-agents)
- WebSearch (for claim verification, run inside sub-agents)

## Files

- `SKILL.md`: This file
