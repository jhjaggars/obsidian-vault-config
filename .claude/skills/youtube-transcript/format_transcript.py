#!/usr/bin/env python3
"""
Format YouTube transcript JSON to timestamped text.

Usage: python3 format_transcript.py <json_file>

Input: JSON file from youtube-transcript-api with format:
[[{"text": "...", "start": 0.0, "duration": 2.5}, ...]]

Output: Timestamped transcript in format:
[HH:MM:SS] transcript text
"""

import json
import sys

def seconds_to_timestamp(seconds):
    """Convert seconds to HH:MM:SS format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 format_transcript.py <json_file>", file=sys.stderr)
        sys.exit(1)

    # Read the JSON transcript
    with open(sys.argv[1], 'r') as f:
        content = f.read()
        data = json.loads(content)

        # The output is wrapped in double brackets [[...]]
        if isinstance(data, list) and len(data) == 1:
            data = data[0]

        # Format as timestamped transcript
        for segment in data:
            timestamp = seconds_to_timestamp(segment['start'])
            text = segment['text']
            print(f"{timestamp} {text}")

if __name__ == "__main__":
    main()
