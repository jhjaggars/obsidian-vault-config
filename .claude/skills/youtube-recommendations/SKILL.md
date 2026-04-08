# YouTube Recommendations Skill

Fetch personalized YouTube recommendations using Playwright with persistent browser session, filter out entertainment, and surface videos worth deep analysis.

## Triggers

- "youtube recommendations"
- "youtube recs"
- "check my youtube recommendations"
- "recommended videos"

## Workflow

When this skill is invoked:

1. **Run the Playwright script** to fetch and classify recommendations. The script opens a headed browser and requires an X server. Always run with `DISPLAY` set — default to `:0` if not already set in the environment:
   ```bash
   DISPLAY=${DISPLAY:-:0} uvx --with playwright python \
     .claude/skills/youtube-recommendations/fetch_playwright_session.py \
     $HOME/ObsidianVault --limit 50
   ```
   If that fails with a display error, ask the user for the correct `$DISPLAY` value (run `echo $DISPLAY` in a desktop terminal) and retry with that value.

   **First run**: The script will open a visible browser window. If not logged in, it will display a message and wait for you to log in manually. The session persists, so subsequent runs are automatic.

   **Subsequent runs**: The script reuses the saved session and runs automatically without requiring login.

2. **Parse the JSON output** which contains classified videos in these arrays:
   - `included`: Videos recommended for analysis
   - `borderline`: Videos needing Claude's judgment
   - `excluded`: Videos filtered out
   - `already_analyzed`: Videos with existing notes in the vault

3. **Classify borderline videos** using Claude's judgment based on:
   - **INCLUDE**: Educational content, technical analysis, investigations, personal finance, design, architecture, technology deep dives
   - **EXCLUDE**: Pure entertainment, memes, reaction videos, celebrity gossip, vlogs, gaming streams

4. **Create recommendation note**: Create `YouTube/YYYY/MM-MonthName/DD-DayName/YYYY-MM-DD-recommendations.md` (using today's date with computed day-of-week) with:

   **Frontmatter**:
   ```yaml
   ---
   source: "youtube-recommendations"
   date: YYYY-MM-DD
   included_count: <number>
   excluded_count: <number>
   already_analyzed_count: <number>
   ---
   ```

   **Sections**:
   - **Recommended for Analysis**: Checklist format
     ```markdown
     ## Recommended for Analysis

     - [ ] [Video Title](url) - Channel Name (duration) - *classification reason*
     ```

   - **Already Analyzed**: Wiki-links to existing notes
     ```markdown
     ## Already Analyzed

     These videos already have analysis notes in your vault:
     - [[Existing Note Title]]
     ```

   - **Excluded** (collapsed): Videos filtered out
     ```markdown
     <details>
     <summary>Excluded Videos (N)</summary>

     - [Video Title](url) - Channel (duration) - *reason*

     </details>
     ```

5. **Present summary**: Show the user:
   - Path to the recommendations note
   - Count of recommended videos
   - Count of already analyzed videos (skipped)
   - Count of excluded videos
   - Reminder to:
     1. Review the recommendations note
     2. Check boxes next to videos they want analyzed
     3. Run `process youtube recommendations` to batch-process all checked videos

## Implementation Notes

- **Date format**: Use ISO format `YYYY-MM-DD` for the filename, with full hierarchical path
- **URL format**: Use full YouTube URLs: `https://www.youtube.com/watch?v={video_id}`
- **Already analyzed matching**: The script recursively scans `YouTube/**/*.md` files and extracts video IDs from frontmatter `url:` fields, so create wiki-links to these notes using their full paths
- **Collapsible sections**: Use `<details>` and `<summary>` tags for the excluded section
- **Error handling**: If the script returns no videos or login errors, check stderr output and follow the on-screen instructions

## Skill Parameters

When invoked, the user may optionally provide:
- `--limit <number>`: Number of recommendations to process (default 50)
- `--skip-categories`: Skip category-based classification for faster results
- `--scroll-count <number>`: Number of scroll operations to load more videos (default 5)

## Configuration

- **Browser**: Uses Playwright Chromium with persistent session (no cookies export needed!)
- **Session persistence**: Login once, sessions persist across runs automatically
- **Profile location**: `~/.cache/ms-playwright/youtube-recs-profile/`
- **Limit**: Processes up to 50 recommendations by default
- **Deduplication**: Automatically excludes videos already analyzed (recursive search of `YouTube/**/*.md` frontmatter)

## Setup (One-Time)

Before first use, install the Playwright Chromium browser:

```bash
uvx --from playwright playwright install chromium
```

**Display requirement**: The script needs an X server. Always run with `DISPLAY=${DISPLAY:-:0}` (defaults to `:0` if unset). If `:0` doesn't work, check the correct value with `echo $DISPLAY` in a desktop terminal.

**First run**: The script will open a visible browser window. If you're not logged into YouTube:
1. You'll see "NOT LOGGED IN - Please log in to YouTube" in the terminal
2. The browser window will be visible - click "Sign in"
3. Log in with your Google account
4. The script automatically detects when you're logged in and continues
5. Your session is saved and persists for future runs

**Subsequent runs**: The script automatically reuses your saved session - no login required!

**If session expires**: The script auto-detects and prompts you to log in again. Just log in manually in the browser window.

## Example Usage

```
User: "youtube recommendations"

Claude:
I'll fetch your YouTube recommendations...

Created: YouTube/2026/02-February/16-Sunday/2026-02-16-recommendations.md

Summary:
- 12 videos recommended for analysis
- 5 already analyzed (skipped)
- 33 excluded (entertainment/music/gaming)

Next steps:
1. Review YouTube/2026/02-February/16-Sunday/2026-02-16-recommendations.md
2. Check boxes next to videos you want analyzed
3. Run `process youtube recommendations` to batch-process all checked videos
```

## Classification Logic

The script uses a two-stage classification process:

**Stage 1 - Title keywords** (fast):
- **INCLUDE**: "explained", "tutorial", "how to", "guide", "analysis", "investigation", "deep dive", "review", "breakdown", "documentary", "news", "report", "interview"
- **EXCLUDE**: "official music video", "lyrics", "gameplay", "walkthrough", "compilation", "asmr", "#shorts", duration < 60s

**Stage 2 - Categories** (optional, for borderline videos):
- **INCLUDE**: News & Politics, Education, Science & Technology, Howto & Style
- **EXCLUDE**: Music, Gaming

Videos that remain borderline after both stages are passed to Claude for final judgment.

## Dependencies

- `playwright` (via `uvx`)
- `yt-dlp` (via `uvx`, for optional category fetching)
- Existing `youtube-transcript` skill for video analysis

## Files

- `fetch_playwright_session.py`: Main script that fetches and classifies recommendations using persistent browser session
- `SKILL.md`: This file
- `README.md`: User documentation
