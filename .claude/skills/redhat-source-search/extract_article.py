#!/usr/bin/env python3
# /// script
# dependencies = ["httpx>=0.28.1", "beautifulsoup4>=4.12"]
# ///
"""
Extract article content from a source.redhat.com page.
Credentials are read from ~/.config/redhat-source/credentials.json.
"""

import json
import sys
from pathlib import Path
import httpx
from bs4 import BeautifulSoup

CREDS_DIR = Path.home() / ".config/redhat-source"


def load_credentials():
    """Load credentials from ~/.config/redhat-source/credentials.json"""
    creds_file = CREDS_DIR / "credentials.json"
    if not creds_file.exists():
        print("Error: credentials not found. Run login.py first.", file=sys.stderr)
        print(f"Expected: {creds_file}", file=sys.stderr)
        sys.exit(1)

    with open(creds_file) as f:
        return json.load(f)


def fetch_and_extract(url: str):
    """Fetch a page and extract article content"""
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

    print(f"Fetching: {url}", file=sys.stderr)
    print(file=sys.stderr)

    with httpx.Client(cookies=cookies, headers=headers, follow_redirects=True, timeout=30.0) as client:
        response = client.get(url)
        response.raise_for_status()

        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract title
        title_tag = soup.find('h1', class_=lambda x: x and 'ig-title' in x)
        title = title_tag.get_text(strip=True) if title_tag else 'No title found'

        # Extract main content - look for various content containers
        content = []

        # Try different content selectors
        content_div = soup.find('div', class_=lambda x: x and any(c in x for c in ['ig-content', 'ig-body', 'article-body']))

        if content_div:
            # Get all text, preserving some structure
            for elem in content_div.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'pre', 'code', 'li', 'blockquote']):
                text = elem.get_text(strip=True)
                if text:
                    if elem.name in ['h1', 'h2', 'h3', 'h4']:
                        content.append(f"\n{text}\n{'='*len(text)}")
                    elif elem.name in ['pre', 'code']:
                        content.append(f"\n{text}\n")
                    else:
                        content.append(text)

        return {
            'url': url,
            'title': title,
            'content': '\n\n'.join(content) if content else 'No content extracted'
        }


def main():
    if len(sys.argv) < 2:
        print("Usage: extract_article.py <url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]

    try:
        article = fetch_and_extract(url)
        print(f"Title: {article['title']}")
        print("=" * 80)
        print(article['content'])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
