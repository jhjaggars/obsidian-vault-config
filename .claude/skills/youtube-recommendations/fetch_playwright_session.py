#!/usr/bin/env python3
"""
Fetch YouTube recommendations using Playwright with persistent browser session.

On first run, opens a visible browser window for manual login. Session persists
across runs via a user data directory, so subsequent runs are automatic.

Usage:
    uvx --with playwright python fetch_playwright_session.py <vault_path> [options]

Example:
    uvx --with playwright python fetch_playwright_session.py \
        $HOME/ObsidianVault --limit 50
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Set


# Classification keywords (case-insensitive)
EXCLUDE_KEYWORDS = [
    "official music video",
    "official video",
    "lyrics",
    "gameplay",
    "playthrough",
    "walkthrough",
    "let's play",
    "stream highlights",
    "funny moments",
    "compilation",
    "asmr",
    "mukbang",
    "#shorts",
]

INCLUDE_KEYWORDS = [
    "explained",
    "tutorial",
    "how to",
    "guide",
    "analysis",
    "investigation",
    "deep dive",
    "review",
    "breakdown",
    "documentary",
    "news",
    "report",
    "interview",
]

# YouTube categories
INCLUDE_CATEGORIES = [
    "News & Politics",
    "Education",
    "Science & Technology",
    "Howto & Style",
]

EXCLUDE_CATEGORIES = [
    "Music",
    "Gaming",
]


def extract_video_id(url: str) -> str:
    """Extract video ID from YouTube URL."""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([^&\s]+)',
        r'youtube\.com/embed/([^&\s]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


def get_existing_video_ids(vault_path: Path) -> Set[str]:
    """Scan YouTube/**/*.md files and extract video IDs from frontmatter."""
    video_ids = set()
    youtube_dir = vault_path / "YouTube"

    if not youtube_dir.exists():
        return video_ids

    for md_file in youtube_dir.glob("**/*.md"):
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # Look for url: in frontmatter
                match = re.search(r'^url:\s*["\']?(https?://[^\s"\']+)["\']?', content, re.MULTILINE)
                if match:
                    url = match.group(1)
                    video_id = extract_video_id(url)
                    if video_id:
                        video_ids.add(video_id)
        except Exception as e:
            print(f"Warning: Could not read {md_file}: {e}", file=sys.stderr)

    return video_ids


def detect_login_state(page) -> bool:
    """
    Detect if user is logged into YouTube using multiple signals.

    Returns: True if logged in, False otherwise
    """
    try:
        # Signal 1: Look for avatar button (logged in users have this)
        avatar_btn = page.query_selector('button#avatar-btn')
        if avatar_btn:
            return True

        # Signal 2: Look for "Sign in" button (not logged in)
        sign_in = page.query_selector('a[href*="accounts.google.com"]')
        if sign_in:
            sign_in_text = sign_in.inner_text().lower()
            if 'sign in' in sign_in_text:
                return False

        # Signal 3: Check if recommendations are loaded (5+ videos)
        video_count = page.evaluate("""
            () => {
                const items = document.querySelectorAll('ytd-rich-item-renderer');
                return items.length;
            }
        """)
        if video_count >= 5:
            return True

        # Signal 4: Check for "Try searching to get started" text (not logged in)
        body_text = page.evaluate("() => document.body.innerText")
        if "try searching to get started" in body_text.lower():
            return False

        # Default to not logged in if uncertain
        return False

    except Exception as e:
        print(f"Warning: Error detecting login state: {e}", file=sys.stderr)
        return False


def wait_for_login(page, timeout: int = 300) -> bool:
    """
    Wait for user to log in manually. Polls every 3 seconds.

    Args:
        page: Playwright page object
        timeout: Maximum wait time in seconds (default: 5 minutes)

    Returns: True if login detected, False if timeout
    """
    print("\n" + "="*60, file=sys.stderr)
    print("NOT LOGGED IN - Please log in to YouTube", file=sys.stderr)
    print("="*60, file=sys.stderr)
    print("", file=sys.stderr)
    print("The browser window should be visible. Please:", file=sys.stderr)
    print("  1. Click 'Sign in' in the browser", file=sys.stderr)
    print("  2. Log in with your Google account", file=sys.stderr)
    print("  3. Wait for YouTube homepage to load", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"Checking every 3 seconds (timeout: {timeout}s)...", file=sys.stderr)
    print("", file=sys.stderr)

    start_time = time.time()
    check_count = 0

    while time.time() - start_time < timeout:
        check_count += 1
        time.sleep(3)

        if detect_login_state(page):
            print(f"\n✓ Login detected after {int(time.time() - start_time)}s!", file=sys.stderr)
            print("", file=sys.stderr)
            return True

        if check_count % 10 == 0:  # Update every 30 seconds
            elapsed = int(time.time() - start_time)
            print(f"Still waiting... ({elapsed}s elapsed)", file=sys.stderr)

    print(f"\n✗ Timeout after {timeout}s - login not detected", file=sys.stderr)
    return False


def dismiss_consent_dialog(page):
    """Dismiss YouTube cookie consent dialog if present."""
    try:
        # Look for common consent dialog patterns
        consent_selectors = [
            'button[aria-label*="Accept"]',
            'button[aria-label*="accept"]',
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
        ]

        for selector in consent_selectors:
            button = page.query_selector(selector)
            if button:
                print("Dismissing consent dialog...", file=sys.stderr)
                button.click()
                page.wait_for_timeout(1000)
                return

    except Exception as e:
        # Not critical if this fails
        print(f"Note: Could not dismiss consent dialog: {e}", file=sys.stderr)


def scroll_and_load(page, count: int = 5, wait_ms: int = 2000):
    """
    Scroll page incrementally to trigger lazy loading of more videos.

    Args:
        page: Playwright page object
        count: Number of scroll operations
        wait_ms: Milliseconds to wait between scrolls
    """
    print(f"Scrolling {count} times to load more recommendations...", file=sys.stderr)

    for i in range(count):
        page.evaluate("""
            () => {
                window.scrollTo(0, document.body.scrollHeight);
            }
        """)
        page.wait_for_timeout(wait_ms)

        # Log progress
        if (i + 1) % 2 == 0:
            print(f"  Scrolled {i + 1}/{count}...", file=sys.stderr)


def parse_duration_str(duration_str: str) -> int:
    """
    Parse YouTube duration string (e.g., "18:45" or "1:23:45") to seconds.

    Returns: Duration in seconds, or 0 if unable to parse
    """
    if not duration_str:
        return 0

    duration_str = duration_str.strip()
    parts = duration_str.split(':')

    try:
        if len(parts) == 2:  # MM:SS
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:  # HH:MM:SS
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            return 0
    except (ValueError, IndexError):
        return 0


def extract_videos(page) -> List[Dict]:
    """
    Extract video data from YouTube homepage using JavaScript evaluation.

    Returns: List of video dictionaries with id, url, title, channel, duration
    """
    print("Extracting video data from page...", file=sys.stderr)

    videos = page.evaluate("""
        () => {
            const videos = [];
            const seen = new Set();

            console.log('Starting video extraction...');

            // Strategy 1: Look for rich item renderers (home page format)
            const richItems = document.querySelectorAll('ytd-rich-item-renderer');
            console.log(`Found ${richItems.length} ytd-rich-item-renderer elements`);

            richItems.forEach(item => {
                // Try multiple link selectors
                const link = item.querySelector('a#video-title-link') ||
                            item.querySelector('a#video-title') ||
                            item.querySelector('a[href*="/watch?v="]');

                if (!link) {
                    console.log('No link found in rich item');
                    return;
                }

                const href = link.href;
                const match = href.match(/[?&]v=([^&]+)/);
                if (!match) return;

                const videoId = match[1];
                if (seen.has(videoId)) return;
                seen.add(videoId);

                const title = link.getAttribute('title') ||
                             link.getAttribute('aria-label') ||
                             link.textContent.trim();

                const channelEl = item.querySelector('ytd-channel-name a') ||
                                 item.querySelector('yt-formatted-string.ytd-channel-name a');
                const channel = channelEl ? channelEl.textContent.trim() : 'Unknown';

                const durationEl = item.querySelector('span.ytd-thumbnail-overlay-time-status-renderer') ||
                                  item.querySelector('#overlays span.ytd-thumbnail-overlay-time-status-renderer');
                const duration = durationEl ? durationEl.textContent.trim() : '';

                videos.push({
                    id: videoId,
                    url: `https://www.youtube.com/watch?v=${videoId}`,
                    title: title,
                    channel: channel,
                    duration_str: duration
                });
            });

            console.log(`After rich items: ${videos.length} videos`);

            // Strategy 2: Grid and list video renderers
            if (videos.length < 5) {
                const gridItems = document.querySelectorAll('ytd-grid-video-renderer, ytd-video-renderer, ytd-compact-video-renderer');
                console.log(`Found ${gridItems.length} grid/video renderer elements`);

                gridItems.forEach(item => {
                    const link = item.querySelector('a#video-title') ||
                                item.querySelector('a.yt-simple-endpoint[href*="/watch?v="]');
                    if (!link) return;

                    const href = link.href;
                    const match = href.match(/[?&]v=([^&]+)/);
                    if (!match) return;

                    const videoId = match[1];
                    if (seen.has(videoId)) return;
                    seen.add(videoId);

                    const title = link.getAttribute('title') ||
                                 link.getAttribute('aria-label') ||
                                 link.textContent.trim();

                    const channelEl = item.querySelector('ytd-channel-name a');
                    const channel = channelEl ? channelEl.textContent.trim() : 'Unknown';

                    const durationEl = item.querySelector('span.ytd-thumbnail-overlay-time-status-renderer');
                    const duration = durationEl ? durationEl.textContent.trim() : '';

                    videos.push({
                        id: videoId,
                        url: `https://www.youtube.com/watch?v=${videoId}`,
                        title: title,
                        channel: channel,
                        duration_str: duration
                    });
                });
            }

            console.log(`After grid items: ${videos.length} videos`);

            // Strategy 3: Fallback - find any links with watch?v=
            if (videos.length < 5) {
                const allLinks = document.querySelectorAll('a[href*="/watch?v="]');
                console.log(`Found ${allLinks.length} total video links`);

                allLinks.forEach(link => {
                    const href = link.href;
                    const match = href.match(/[?&]v=([^&]+)/);
                    if (!match) return;

                    const videoId = match[1];
                    if (seen.has(videoId)) return;
                    seen.add(videoId);

                    // Try to get title from various sources
                    let title = link.getAttribute('title') ||
                               link.getAttribute('aria-label');

                    // If no title attribute, look for title element in parent
                    if (!title || title.length < 3) {
                        const parent = link.closest('ytd-rich-item-renderer, ytd-video-renderer, ytd-grid-video-renderer, ytd-compact-video-renderer');
                        if (parent) {
                            const titleEl = parent.querySelector('#video-title') ||
                                          parent.querySelector('.title') ||
                                          parent.querySelector('yt-formatted-string#video-title');
                            if (titleEl) {
                                title = titleEl.textContent.trim();
                            }
                        }
                    }

                    // Skip if title looks like a duration (matches XX:XX pattern)
                    if (!title || /^\d{1,2}:\d{2}$/.test(title.trim())) {
                        title = 'Unknown';
                    }

                    // Try to find channel
                    let channel = 'Unknown';
                    const parent = link.closest('ytd-rich-item-renderer, ytd-video-renderer, ytd-grid-video-renderer, ytd-compact-video-renderer');
                    if (parent) {
                        const channelEl = parent.querySelector('ytd-channel-name a') ||
                                        parent.querySelector('yt-formatted-string.ytd-channel-name a') ||
                                        parent.querySelector('#channel-name a');
                        if (channelEl) {
                            channel = channelEl.textContent.trim();
                        }
                    }

                    // Try to find duration
                    let duration = '';
                    if (parent) {
                        const durationEl = parent.querySelector('span.ytd-thumbnail-overlay-time-status-renderer');
                        if (durationEl) {
                            duration = durationEl.textContent.trim();
                        }
                    }

                    videos.push({
                        id: videoId,
                        url: `https://www.youtube.com/watch?v=${videoId}`,
                        title: title,
                        channel: channel,
                        duration_str: duration
                    });
                });
            }

            console.log(`Final count: ${videos.length} videos`);
            return videos;
        }
    """)

    # Parse duration strings to seconds
    for video in videos:
        duration_str = video.get('duration_str', '')
        video['duration'] = parse_duration_str(duration_str)

    print(f"Extracted {len(videos)} videos", file=sys.stderr)

    # If we got videos but they're missing metadata, fetch it with yt-dlp
    videos_missing_metadata = [v for v in videos if v.get('title') == 'Unknown' or v.get('title', '').count(':') >= 1 and len(v.get('title', '')) < 10]

    if videos_missing_metadata:
        print(f"Fetching metadata for {len(videos_missing_metadata)} videos with missing/bad titles...", file=sys.stderr)
        for idx, video in enumerate(videos_missing_metadata, 1):
            if idx % 5 == 0:
                print(f"  Fetching metadata... ({idx}/{len(videos_missing_metadata)})", file=sys.stderr)

            metadata = get_full_metadata(video['id'])
            if metadata:
                video['title'] = metadata.get('title', video['title'])
                video['channel'] = metadata.get('uploader', video.get('channel', 'Unknown'))
                if 'duration' in metadata:
                    video['duration'] = metadata['duration']
                    video['duration_str'] = format_duration(metadata['duration'])

    return videos


def classify_by_title(title: str, duration: int) -> str:
    """
    Classify video by title keywords.

    Returns: "include", "exclude", or "borderline"
    """
    # Skip shorts (< 60 seconds)
    if duration > 0 and duration < 60:
        return "exclude"

    title_lower = title.lower()

    # Check exclude patterns first
    for keyword in EXCLUDE_KEYWORDS:
        if keyword in title_lower:
            return "exclude"

    # Check include patterns
    for keyword in INCLUDE_KEYWORDS:
        if keyword in title_lower:
            return "include"

    return "borderline"


def classify_by_category(categories: List[str]) -> str:
    """
    Classify video by YouTube category.

    Returns: "include", "exclude", or "borderline"
    """
    if not categories:
        return "borderline"

    for category in categories:
        if category in INCLUDE_CATEGORIES:
            return "include"
        if category in EXCLUDE_CATEGORIES:
            return "exclude"

    return "borderline"


def format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS or MM:SS."""
    if seconds == 0:
        return "Unknown"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def get_full_metadata(video_id: str) -> Dict:
    """Fetch full metadata for a specific video to get categories."""
    cmd = [
        "uvx", "yt-dlp",
        "--dump-json",
        "--no-download",
        f"https://www.youtube.com/watch?v={video_id}"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        print(f"Warning: Could not fetch full metadata for {video_id}: {e}", file=sys.stderr)
        return {}


def main():
    parser = argparse.ArgumentParser(
        description="Fetch YouTube recommendations using Playwright persistent session"
    )
    parser.add_argument("vault_path", type=Path, help="Path to Obsidian vault")
    parser.add_argument("--limit", type=int, default=50, help="Max videos to process (default: 50)")
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path.home() / ".cache" / "ms-playwright" / "youtube-recs-profile",
        help="Browser profile directory for persistent session"
    )
    parser.add_argument(
        "--scroll-count",
        type=int,
        default=5,
        help="Number of scroll operations to load more videos (default: 5)"
    )
    parser.add_argument(
        "--skip-categories",
        action="store_true",
        help="Skip category-based classification (faster, but less accurate)"
    )
    parser.add_argument(
        "--login-timeout",
        type=int,
        default=300,
        help="Max seconds to wait for login (default: 300)"
    )

    args = parser.parse_args()

    # Check if playwright is available
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(json.dumps({
            "error": "Playwright not installed. Run: uvx --from playwright playwright install chromium",
            "included": [],
            "borderline": [],
            "excluded": [],
            "already_analyzed": []
        }))
        sys.exit(1)

    # Get existing video IDs
    print(f"Scanning {args.vault_path}/YouTube/ for existing videos...", file=sys.stderr)
    existing_ids = get_existing_video_ids(args.vault_path)
    print(f"Found {len(existing_ids)} already analyzed videos", file=sys.stderr)
    print("", file=sys.stderr)

    # Launch browser with persistent context
    print(f"Launching browser with persistent profile at {args.profile_dir}...", file=sys.stderr)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(args.profile_dir),
            headless=False,
            viewport={'width': 1280, 'height': 900},
            # Remove automation flags to avoid Google detection
            args=[
                '--disable-blink-features=AutomationControlled',
            ],
            ignore_default_args=[
                '--enable-automation',
            ],
        )

        page = context.pages[0] if context.pages else context.new_page()

        # Navigate to YouTube
        print("Navigating to YouTube...", file=sys.stderr)
        page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        # Dismiss consent dialog if present
        dismiss_consent_dialog(page)
        page.wait_for_timeout(1000)

        # Check login state
        print("Checking login state...", file=sys.stderr)
        is_logged_in = detect_login_state(page)

        if not is_logged_in:
            # Wait for user to log in
            if not wait_for_login(page, timeout=args.login_timeout):
                context.close()
                print(json.dumps({
                    "error": "Login timeout - please try again and log in within the timeout period",
                    "included": [],
                    "borderline": [],
                    "excluded": [],
                    "already_analyzed": []
                }))
                sys.exit(1)

            # Refresh page after login to ensure we're on the homepage
            print("Refreshing page after login...", file=sys.stderr)
            page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
        else:
            print("✓ Already logged in", file=sys.stderr)
            print("", file=sys.stderr)

        # Scroll to load more recommendations
        scroll_and_load(page, count=args.scroll_count)
        print("", file=sys.stderr)

        # Extract videos
        videos = extract_videos(page)

        # Take screenshot for debugging
        try:
            screenshot_path = "/tmp/youtube-playwright-session.png"
            page.screenshot(path=screenshot_path)
            print(f"Screenshot saved to {screenshot_path}", file=sys.stderr)
        except Exception as e:
            print(f"Note: Could not save screenshot: {e}", file=sys.stderr)

        # Close browser
        context.close()

    print("", file=sys.stderr)
    print(f"Processing {len(videos)} videos...", file=sys.stderr)

    # Classify videos
    included = []
    borderline = []
    excluded = []
    already_analyzed = []

    for idx, video in enumerate(videos, 1):
        video_id = video.get("id", "")
        title = video.get("title", "Unknown")
        url = video.get("url", "")
        channel = video.get("channel", "Unknown")
        duration = video.get("duration", 0)
        duration_formatted = format_duration(duration)

        # Skip if already analyzed
        if video_id in existing_ids:
            already_analyzed.append({
                "id": video_id,
                "title": title,
                "url": url,
                "channel": channel,
                "duration_formatted": duration_formatted
            })
            continue

        # Stage 1: Title-based classification
        classification = classify_by_title(title, duration)

        if classification == "include":
            included.append({
                "id": video_id,
                "title": title,
                "url": url,
                "channel": channel,
                "duration_formatted": duration_formatted,
                "reason": "title keywords"
            })
        elif classification == "exclude":
            excluded.append({
                "id": video_id,
                "title": title,
                "url": url,
                "channel": channel,
                "duration_formatted": duration_formatted,
                "reason": "title keywords or too short"
            })
        else:
            # Borderline - optionally do Stage 2 category classification
            if args.skip_categories:
                borderline.append({
                    "id": video_id,
                    "title": title,
                    "url": url,
                    "channel": channel,
                    "duration_formatted": duration_formatted,
                    "categories": []
                })
            else:
                # Stage 2: Category-based classification
                if idx % 10 == 0:
                    print(f"  Fetching categories for borderline videos... ({idx}/{len(videos)})", file=sys.stderr)

                full_metadata = get_full_metadata(video_id)
                categories = full_metadata.get("categories", [])
                category_classification = classify_by_category(categories)

                if category_classification == "include":
                    included.append({
                        "id": video_id,
                        "title": title,
                        "url": url,
                        "channel": channel,
                        "duration_formatted": duration_formatted,
                        "reason": f"category: {', '.join(categories)}"
                    })
                elif category_classification == "exclude":
                    excluded.append({
                        "id": video_id,
                        "title": title,
                        "url": url,
                        "channel": channel,
                        "duration_formatted": duration_formatted,
                        "reason": f"category: {', '.join(categories)}"
                    })
                else:
                    # Still borderline after category check
                    borderline.append({
                        "id": video_id,
                        "title": title,
                        "url": url,
                        "channel": channel,
                        "duration_formatted": duration_formatted,
                        "categories": categories
                    })

        # Stop if we've hit the limit
        if len(included) + len(borderline) + len(excluded) >= args.limit:
            break

    print("", file=sys.stderr)
    print("Classification complete!", file=sys.stderr)
    print(f"  Included: {len(included)}", file=sys.stderr)
    print(f"  Borderline: {len(borderline)}", file=sys.stderr)
    print(f"  Excluded: {len(excluded)}", file=sys.stderr)
    print(f"  Already analyzed: {len(already_analyzed)}", file=sys.stderr)
    print("", file=sys.stderr)

    # Output results as JSON
    result = {
        "included": included,
        "borderline": borderline,
        "excluded": excluded,
        "already_analyzed": already_analyzed,
        "counts": {
            "total_fetched": len(videos),
            "included": len(included),
            "borderline": len(borderline),
            "excluded": len(excluded),
            "already_analyzed": len(already_analyzed)
        }
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
