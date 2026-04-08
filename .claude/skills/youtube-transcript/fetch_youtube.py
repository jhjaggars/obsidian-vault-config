#!/usr/bin/env python3
"""
Fetch YouTube video metadata and transcript.

Usage: python3 fetch_youtube.py VIDEO_ID

Outputs JSON with:
{
  "metadata": {
    "title": "...",
    "channel": "...",
    "published": "YYYY-MM-DD",
    "description": "...",
    "duration": 1234
  },
  "transcript": [
    {"text": "...", "start": 0.0, "duration": 2.5},
    ...
  ]
}
"""

import json
import sys
import subprocess
from datetime import datetime

def fetch_metadata(video_id):
    """Fetch video metadata using yt-dlp"""
    try:
        result = subprocess.run(
            ['uvx', 'yt-dlp', '--dump-json', '--no-download',
             f'https://www.youtube.com/watch?v={video_id}'],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)

        # Convert upload_date from YYYYMMDD to YYYY-MM-DD
        upload_date = data.get('upload_date', '')
        if upload_date and len(upload_date) == 8:
            published = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
        else:
            published = datetime.now().strftime('%Y-%m-%d')

        return {
            'title': data.get('title', 'Unknown Title'),
            'channel': data.get('channel') or data.get('uploader', 'Unknown Channel'),
            'published': published,
            'description': data.get('description', ''),
            'duration': data.get('duration', 0)
        }
    except Exception as e:
        print(f"Error fetching metadata: {e}", file=sys.stderr)
        return None

def fetch_transcript(video_id):
    """Fetch transcript using youtube-transcript-api Python module"""
    try:
        # Use Python directly with the module
        script = f"""
from youtube_transcript_api import YouTubeTranscriptApi
import json
transcript = YouTubeTranscriptApi.get_transcript('{video_id}')
print(json.dumps(transcript))
"""
        result = subprocess.run(
            ['uvx', '--from', 'youtube-transcript-api', '--with', 'youtube-transcript-api',
             'python3', '-c', script],
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Error fetching transcript: {e}", file=sys.stderr)
        print(f"STDERR: {result.stderr if 'result' in locals() else 'N/A'}", file=sys.stderr)
        return None

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 fetch_youtube.py VIDEO_ID", file=sys.stderr)
        sys.exit(1)

    video_id = sys.argv[1]

    metadata = fetch_metadata(video_id)
    transcript = fetch_transcript(video_id)

    if metadata is None or transcript is None:
        sys.exit(1)

    output = {
        'metadata': metadata,
        'transcript': transcript
    }

    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
