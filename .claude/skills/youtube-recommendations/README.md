# YouTube Recommendations Skill

Automatically fetch your personalized YouTube recommendations using Playwright with persistent browser sessions, filter out entertainment content, and create a checklist of videos worth deep analysis.

## Quick Start

```bash
# First time setup: Install Playwright Chromium browser
uvx --from playwright playwright install chromium

# Then invoke via Claude:
youtube recommendations

# First run: Log in manually in the browser window when prompted
# Subsequent runs: Automatic (session persists)
```

## How It Works

1. **Launches** Playwright with a persistent browser session (login persists across runs)
2. **Detects login state** and waits if you need to log in (first run or expired session)
3. **Scrapes** YouTube homepage recommendations by scrolling and extracting video data
4. **Deduplicates** by recursively checking existing `YouTube/**/*.md` notes
5. **Classifies** videos in two stages:
   - **Stage 1**: Title-based keyword matching (fast)
   - **Stage 2**: YouTube category for borderline videos (optional, can skip with `--skip-categories`)
6. **Creates** a checklist note in `YouTube/YYYY-MM-DD-recommendations.md`
7. **You review** and check boxes next to videos you want analyzed
8. **You run** `/youtube transcript <url>` on checked videos

## Classification Logic

### Automatically Included
- Title keywords: "explained", "tutorial", "how to", "guide", "analysis", "investigation", "deep dive", "review", "breakdown", "documentary", "news", "report", "interview"
- Categories: News & Politics, Education, Science & Technology, Howto & Style

### Automatically Excluded
- Title keywords: "official music video", "official video", "lyrics", "gameplay", "playthrough", "walkthrough", "let's play", "stream highlights", "funny moments", "compilation", "asmr", "mukbang", "#shorts"
- Categories: Music, Gaming
- Duration: Videos under 60 seconds

### Borderline (Claude's Judgment)
Videos that don't match include/exclude patterns are reviewed by Claude based on:
- Content type (educational vs entertainment)
- Topic relevance (technology, finance, investigations vs celebrity gossip, memes)

## Setup: One-Time Installation

1. **Install Playwright Chromium browser** (one-time setup):
   ```bash
   uvx --from playwright playwright install chromium
   ```

2. **First run**: When you invoke the skill for the first time, a browser window will open:
   - If you're not logged into YouTube, the terminal will show: "NOT LOGGED IN - Please log in to YouTube"
   - Log in manually in the visible browser window
   - The script auto-detects when you're logged in and continues
   - Your session is saved to `~/.cache/ms-playwright/youtube-recs-profile/`

3. **Subsequent runs**: Your session persists! No login needed, the script runs automatically.

### Session Expiration

If your session expires (usually after weeks/months):
1. The script will auto-detect and show "NOT LOGGED IN" again
2. Log in manually in the browser window
3. The script continues automatically
4. Your new session is saved for future runs

## Files

```
.claude/skills/youtube-recommendations/
├── README.md                      # This file
├── SKILL.md                        # Skill definition for Claude
└── fetch_playwright_session.py   # Main script (Playwright with persistent session)
```

## Testing

Test the script directly:

```bash
# Basic test (will open browser for login if needed)
uvx --with playwright python \
  .claude/skills/youtube-recommendations/fetch_playwright_session.py \
  $HOME/ObsidianVault --limit 10

# If using tmux or Wayland, you may need to set DISPLAY
DISPLAY=:0 uvx --with playwright python \
  .claude/skills/youtube-recommendations/fetch_playwright_session.py \
  $HOME/ObsidianVault --limit 10

# Fast test (skip category classification)
uvx --with playwright python \
  .claude/skills/youtube-recommendations/fetch_playwright_session.py \
  $HOME/ObsidianVault --limit 10 --skip-categories

# Load more videos with extra scrolling
uvx --with playwright python \
  .claude/skills/youtube-recommendations/fetch_playwright_session.py \
  $HOME/ObsidianVault --limit 50 --scroll-count 10
```

Expected output: JSON with `included`, `borderline`, `excluded`, and `already_analyzed` arrays.

## Troubleshooting

### "Playwright not installed"

**Cause**: Playwright browser not installed

**Solution**:
```bash
uvx --from playwright playwright install chromium
```

### "NOT LOGGED IN" message appears

**Expected behavior**: This is normal on first run or when session expires.

**Solution**:
1. Don't close the browser window that opened
2. Click "Sign in" in the browser
3. Log in with your Google account
4. Wait for the script to detect login (checks every 3 seconds)
5. Session will be saved for future runs

### "Login timeout" error

**Cause**: Didn't log in within the timeout period (default 5 minutes)

**Solution**:
- Run the command again
- Log in promptly when the browser opens
- Or increase timeout: `--login-timeout 600` (10 minutes)

### Browser window doesn't appear or "Missing X server" error

**Cause**: Running in tmux or from a terminal without proper display configuration

**Solution**: Set the DISPLAY environment variable:
```bash
# For most systems (try :0 first, then :1)
DISPLAY=:0 uvx --with playwright python \
  .claude/skills/youtube-recommendations/fetch_playwright_session.py \
  $HOME/ObsidianVault --limit 10

# Or export it for the session
export DISPLAY=:0
```

**Wayland users**: XWayland should handle this automatically with `:0`. If you still have issues, try running outside of tmux in a regular terminal window.

### Videos keep appearing in recommendations

**Cause**: Video hasn't been analyzed yet (no note in `YouTube/` folder)

**Solution**:
- Run `/youtube transcript <url>` to create analysis note
- The video will be automatically excluded next time

### Session expired

**Cause**: YouTube sessions expire after weeks/months

**Solution**: The script auto-detects this and prompts you to log in again. Just log in manually in the browser window.

## Integration

This skill works with the existing `youtube-transcript` skill:

1. **youtube-recommendations** → Creates checklist note
2. **You review** → Check boxes next to videos to analyze
3. **youtube-transcript** → Analyze each checked video
4. **Result** → Videos are excluded from future recommendations

## Example Output

`YouTube/2026-02-16-recommendations.md`:

```markdown
---
source: "youtube-recommendations"
date: 2026-02-16
included_count: 12
excluded_count: 33
already_analyzed_count: 5
---

## Recommended for Analysis

- [ ] [How Quantum Computing Will Change Everything](url) - Veritasium (18:45) - *title keywords*
- [ ] [The Economics of Cloud Computing Explained](url) - TechChannel (25:12) - *category: Education*

## Already Analyzed

These videos already have analysis notes in your vault:
- [[Understanding Docker Containers - 2026-02-15]]
- [[Machine Learning Basics - 2026-02-14]]

<details>
<summary>Excluded Videos (33)</summary>

- [Some Music Video](url) - Artist (3:45) - *title keywords*
- [Gaming Stream Highlights](url) - Streamer (12:30) - *title keywords*

</details>
```

## Command Line Options

```bash
# Basic usage
uvx --with playwright python fetch_playwright_session.py <vault_path> [options]

# With DISPLAY for tmux/Wayland users
DISPLAY=:0 uvx --with playwright python fetch_playwright_session.py <vault_path> [options]

Options:
  --limit N                Number of videos to process (default: 50)
  --profile-dir PATH       Browser profile directory (default: ~/.cache/ms-playwright/youtube-recs-profile)
  --scroll-count N         Number of scroll operations (default: 5)
  --skip-categories        Skip category-based classification (faster)
  --login-timeout N        Max seconds to wait for login (default: 300)
```

**Note for tmux/Wayland users**: If you get "Missing X server" errors, prefix commands with `DISPLAY=:0` to use XWayland.
