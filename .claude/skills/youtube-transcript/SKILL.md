---
name: youtube-transcript
description: "Download a YouTube video transcript and save it to Obsidian with metadata and analysis. Creates two linked notes: a raw transcript with timestamps and a detailed analysis with independent verification of key ideas. Triggers on: youtube transcript, save youtube video, analyze youtube video, transcript for, youtube to obsidian."
---

# YouTube Transcript Skill

This skill downloads a YouTube video transcript, extracts metadata, and creates two linked Obsidian notes:
1. A raw transcript note with timestamps and metadata
2. An analysis note with summary and independent verification of key claims

## Workflow

### Step 1: Extract Video ID & Fetch Metadata

When the user provides a YouTube URL, parse the video ID from these formats:
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://m.youtube.com/watch?v=VIDEO_ID`

Use `uvx yt-dlp` to extract video metadata without downloading:
```bash
uvx yt-dlp --dump-json --no-download "VIDEO_URL" | jq '{title, uploader, channel, upload_date, description, duration}'
```

This returns JSON with comprehensive metadata including:
- `title`: Video title
- `uploader` or `channel`: Channel name (speaker/creator)
- `upload_date`: Publish date in YYYYMMDD format (convert to YYYY-MM-DD)
- `description`: Video description
- `duration`: Duration in seconds

From the JSON output, extract:
- Video title (from `title`)
- Channel name (from `uploader` or `channel`)
- Publish date (from `upload_date`, convert YYYYMMDD to YYYY-MM-DD)
- Description (from `description`)

Use your judgment to categorize the video based on title, description, and channel context:
- tutorial, lecture, interview, conference talk, documentary, podcast, news, entertainment, etc.

Identify speakers from the channel name, video description, and transcript content.

### Step 2: Fetch Transcript

Run this command to get the transcript with timestamps:
```bash
uvx --from youtube-transcript-api youtube_transcript_api --format=json -- VIDEO_ID > /tmp/transcript.json
```

**Important**:
- Use `--format=json` (with `=` sign)
- Use `--` before the video ID to prevent video IDs starting with `-` from being interpreted as flags
- Redirect to a file to capture clean JSON output

The output is JSON with timestamps for each segment:
```json
[[{"text": "Hello everyone", "start": 0.0, "duration": 2.5},
  {"text": "Today we're talking about...", "start": 2.5, "duration": 3.2}]]
```

Note: The output is wrapped in double brackets `[[...]]`.

Format the transcript using the helper script:
```bash
python3 .claude/skills/youtube-transcript/format_transcript.py /tmp/transcript.json
```

This converts the JSON to timestamped format:
```
[00:00:00] Hello everyone
[00:00:02] Today we're talking about...
```

If the transcript is unavailable (command fails or returns error), report the error to the user and stop.

### Step 3: Create Raw Transcript Note

**Filepath**: `YouTube/YYYY/MM-MonthName/DD-DayName/YYYY-MM-DD-Slugified-Video-Title.md`
- Date components come from the video's publish date (compute day-of-week from the date)
- Slugify the title (lowercase, hyphens, remove special chars, limit length to ~60 chars)
- Create the full date hierarchy with `mkdir -p YouTube/YYYY/MM-MonthName/DD-DayName`

**Frontmatter**:
```yaml
---
title: "Full Video Title"
url: "https://www.youtube.com/watch?v=VIDEO_ID"
channel: "Channel Name"
speakers:
  - "Speaker Name"
published: YYYY-MM-DD
category: "lecture"
duration: 1234
source: "youtube"
analysis: "[[YouTube/YYYY/MM-MonthName/DD-DayName/YYYY-MM-DD-Slugified-Video-Title - Analysis]]"
---
```

**Note**: `duration` is the video length in seconds (from the `duration` field in yt-dlp metadata).

**YAML validation**: After constructing the frontmatter block, validate it with Python before writing the file:
```bash
python3 -c "
import yaml, sys
frontmatter = '''
title: \"...\"
url: \"...\"
...
'''
try:
    yaml.safe_load(frontmatter)
    print('OK')
except yaml.YAMLError as e:
    print(f'INVALID: {e}', file=sys.stderr)
    sys.exit(1)
"
```
If validation fails, fix the offending field(s) using these rules:
- Value contains double quotes → wrap in single quotes: `title: 'Has "quotes" inside'`
- Value contains single quotes → wrap in double quotes and escape, or use a YAML block scalar
- Value contains a colon followed by a space → wrap in quotes
- Value contains a leading `#`, `[`, `{`, `|`, `>`, or `!` → wrap in quotes

Fix and re-validate before writing.

**Body**:
```markdown
# Full Video Title

**Channel**: Channel Name
**Published**: YYYY-MM-DD
**URL**: [Watch on YouTube](https://www.youtube.com/watch?v=VIDEO_ID)
**Category**: lecture
**Analysis**: [[YouTube/YYYY/MM-MonthName/DD-DayName/YYYY-MM-DD-Slugified-Video-Title - Analysis]]

## Transcript

[00:00:00] First segment text
[00:00:05] Next segment text
...
```

### Step 4: Analyze Transcript & Verify Claims

Read through the transcript and:

1. **Summarize** the content (main topic, key arguments, conclusions)
2. **Extract key points** — the most important takeaways (5-10 bullets)
3. **Identify notable claims** — 3-5 specific claims, statistics, or ideas worth verifying
   - Look for factual assertions, statistics, historical claims, or technical explanations
   - Prefer verifiable facts over opinions

For each claim identified:
- Use `WebSearch` to independently verify it
- Search for authoritative sources (academic, journalistic, official documentation)
- Determine verification status:
  - **Confirmed**: Found reliable sources that support the claim
  - **Partially supported**: Some evidence exists but with caveats
  - **Contested**: Found contradictory evidence or debate
  - **Unverifiable**: Cannot find reliable sources either way

Document:
- The claim as stated in the video
- Verification result
- Supporting/contradictory evidence found
- Source URLs (as markdown links with descriptive text)

Also note any related resources or further reading discovered during verification.

### Step 5: Create Analysis Note

**Filepath**: `YouTube/YYYY/MM-MonthName/DD-DayName/YYYY-MM-DD-Slugified-Video-Title - Analysis.md`
- Same date hierarchy and slug as the transcript note, with " - Analysis" suffix

**Frontmatter**:
```yaml
---
title: "Analysis: Full Video Title"
url: "https://www.youtube.com/watch?v=VIDEO_ID"
channel: "Channel Name"
published: YYYY-MM-DD
source: "youtube-analysis"
transcript: "[[YouTube/YYYY/MM-MonthName/DD-DayName/YYYY-MM-DD-Slugified-Video-Title]]"
---
```

**Body**:
```markdown
# Analysis: Full Video Title

**Transcript**: [[YouTube/YYYY/MM-MonthName/DD-DayName/YYYY-MM-DD-Slugified-Video-Title]]
**Channel**: Channel Name
**Published**: YYYY-MM-DD
**URL**: [Watch on YouTube](https://www.youtube.com/watch?v=VIDEO_ID)

## Summary

2-3 paragraph overview of the video's content, main arguments, and conclusions.

## Key Points

- First key takeaway
- Second key takeaway
- Third key takeaway
- ...

## Verification

### Claim 1: "Specific claim from video"

**Status**: Confirmed / Partially supported / Contested / Unverifiable

**Evidence**: Description of what was found during verification. Include supporting or contradictory evidence.

**Sources**:
- [Descriptive link text](https://example.com/source1)
- [Another source](https://example.com/source2)

### Claim 2: "Another specific claim"

**Status**: ...

**Evidence**: ...

**Sources**: ...

(Repeat for each verified claim)

## Related Resources

Links discovered during verification that provide additional context:
- [Resource title](https://example.com) - Brief description
- [Another resource](https://example.com) - Brief description

## Transcript

Full timestamped transcript: [[YouTube/YYYY/MM-MonthName/DD-DayName/YYYY-MM-DD-Slugified-Video-Title]]
```

### Step 6: Report Results

After creating both notes, tell the user:
1. Where the transcript note was saved
2. Where the analysis note was saved
3. The video title, channel, and publish date
4. Summary of verification results:
   - How many claims were verified
   - Highlight any claims that were contested or unverifiable
   - Mention particularly interesting findings

## Error Handling

- If the video ID cannot be parsed, ask the user for clarification
- If `youtube-transcript-api` fails (no transcript available, video private/deleted), report the specific error
- If `yt-dlp` fails to get metadata, use fallback values (extract title from URL if possible, "Unknown Channel", today's date) and note this to the user
- If WebSearch is unavailable or fails, create the analysis note without verification section and note this limitation

## Notes

- Create the full date hierarchy with `mkdir -p YouTube/YYYY/MM-MonthName/DD-DayName`
- Use bidirectional linking: transcript → analysis and analysis → transcript
- The `source: "youtube"` and `source: "youtube-analysis"` frontmatter enables Dataview/Base queries across all YouTube content
- Timestamps in `[HH:MM:SS]` format make transcripts easy to scan and reference
- Date-prefixed filenames with hierarchical organization keep notes chronologically sortable
- Always validate frontmatter YAML with `python3 -c "import yaml; yaml.safe_load(open('file.md').read().split('---')[1])"` after writing each note; fix any parse errors before proceeding
