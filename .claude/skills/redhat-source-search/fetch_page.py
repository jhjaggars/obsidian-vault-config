#!/usr/bin/env python3
# /// script
# dependencies = ["httpx>=0.28.1"]
# ///
"""
Fetch a source.redhat.com page using saved credentials.
Credentials are read from ~/.config/redhat-source/credentials.json.
"""

import json
import sys
from pathlib import Path
import httpx

CREDS_DIR = Path.home() / ".config/redhat-source"


def load_credentials():
    """Load credentials from ~/.config/redhat-source/credentials.json"""
    creds_file = CREDS_DIR / "credentials.json"
    if not creds_file.exists():
        print("Error: credentials not found. Run login.py first.")
        print(f"Expected: {creds_file}")
        sys.exit(1)

    with open(creds_file) as f:
        return json.load(f)


def fetch_page(url: str):
    """Fetch a page using saved credentials"""
    creds = load_credentials()

    # Build cookies dict from saved credentials
    cookies = {}
    for cookie in creds['cookies']:
        cookies[cookie['name']] = cookie['value']

    # Set up headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    # Add any auth headers from credentials
    if creds.get('auth_headers'):
        headers.update(creds['auth_headers'])

    print(f"Fetching: {url}")
    print()

    with httpx.Client(cookies=cookies, headers=headers, follow_redirects=True, timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def main():
    if len(sys.argv) < 2:
        print("Usage: fetch_page.py <url>")
        sys.exit(1)

    url = sys.argv[1]

    try:
        content = fetch_page(url)
        print(content)
    except Exception as e:
        print(f"Error fetching page: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
