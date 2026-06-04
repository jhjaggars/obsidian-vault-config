#!/usr/bin/env python3
# /// script
# dependencies = ["httpx>=0.28.1"]
# ///
"""
Search source.redhat.com using the discovered API endpoints.

This uses the actual search API that the website uses internally.
Credentials are read from ~/.config/redhat-source/credentials.json.
"""

import json
import sys
from pathlib import Path
from typing import Dict
import httpx

CREDS_DIR = Path.home() / ".config/redhat-source"


class SourceRedHatSearch:
    """Search API client for source.redhat.com."""

    def __init__(self, credentials_file: str = None):
        self.credentials_file = Path(credentials_file) if credentials_file else CREDS_DIR / "credentials.json"
        self.base_url = "https://source.redhat.com"
        self.community_id = "10"  # Discovered from network traffic
        self.credentials = None
        self.cookies = None
        self.headers = None

    def load_credentials(self):
        """Load saved credentials."""
        if not self.credentials_file.exists():
            raise FileNotFoundError(
                f"Credentials file not found: {self.credentials_file}\n"
                "Run: uv run .claude/skills/redhat-source-search/login.py\n"
                "(Credentials are stored in ~/.config/redhat-source/)"
            )

        with open(self.credentials_file) as f:
            self.credentials = json.load(f)

        # Build cookies
        self.cookies = {c['name']: c['value'] for c in self.credentials['cookies']}

        # Build headers matching the observed API calls
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': self.base_url + '/'
        }

    def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        detailed: bool = True
    ) -> Dict:
        """
        Search source.redhat.com.

        Args:
            query: Search query string
            limit: Number of results to return (default: 20)
            offset: Offset for pagination (default: 0)
            detailed: Use detailed search endpoint (default: True)

        Returns:
            Dictionary containing search results
        """
        if not self.cookies:
            self.load_credentials()

        # Choose endpoint
        if detailed:
            endpoint = f"/.api2/api/v1/communities/{self.community_id}/search/contentdetailed"
            params = {
                'query': query,
                'limit': limit,
                'offset': offset,
                'includeMicroblog': 'true',
                'includeArchived': 'false',
                'facetFields': '92'
            }
        else:
            endpoint = f"/.api2/api/v1/communities/{self.community_id}/search/content"
            params = {
                'query': query,
                'limit': limit,
                'offset': offset,
                'parentHref': ''
            }

        url = self.base_url + endpoint

        print(f"Searching: {query}")
        print(f"API: {endpoint}")
        print(f"Limit: {limit}, Offset: {offset}\n")

        with httpx.Client(cookies=self.cookies, headers=self.headers, follow_redirects=True) as client:
            response = client.get(url, params=params, timeout=30.0)

            if response.status_code == 200:
                return response.json()
            elif response.status_code in [401, 403]:
                raise Exception(
                    f"Authentication failed (status {response.status_code}). "
                    "Credentials may be expired. Re-run: uv run .claude/skills/redhat-source-search/login.py"
                )
            else:
                raise Exception(f"Search failed with status {response.status_code}: {response.text}")

    def format_results(self, results: Dict) -> str:
        """Format search results for display."""
        output = []

        # Check if results have the expected structure
        if 'fusionQueryId' in results and 'results' in results:
            # Detailed search response
            items = results['results']
            total = len(items)

            output.append(f"Found {total} results\n")
            output.append("="*80)

            for i, item in enumerate(items, 1):
                output.append(f"\n{i}. {item.get('title', 'Untitled')}")
                output.append(f"   Type: {item.get('objectType', 'unknown')}")
                output.append(f"   URL: {self.base_url}{item.get('href', '')}")

                if item.get('description'):
                    desc = item['description'][:200]
                    output.append(f"   Description: {desc}...")

                if item.get('createdByFullName'):
                    output.append(f"   Created by: {item['createdByFullName']}")

                if item.get('modifiedDate'):
                    output.append(f"   Modified: {item['modifiedDate']}")

        elif 'response' in results and 'items' in results.get('response', {}):
            # Simple search response
            items = results['response']['items']
            total = results['response'].get('totalCount', len(items))

            output.append(f"Found {total} total results (showing {len(items)})\n")
            output.append("="*80)

            for i, item in enumerate(items, 1):
                output.append(f"\n{i}. {item.get('title', 'Untitled')}")
                output.append(f"   Type: {item.get('__type', 'unknown')}")
                output.append(f"   URL: {self.base_url}{item.get('href', '')}")

        else:
            output.append("Unexpected response format:")
            output.append(json.dumps(results, indent=2)[:1000])

        return "\n".join(output)


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        print("Usage: uv run search.py <search query>")
        print("Example: uv run search.py service delivery")
        sys.exit(1)

    try:
        searcher = SourceRedHatSearch()
        searcher.load_credentials()

        # Perform search
        results = searcher.search(query, limit=20)

        # Display results
        print(searcher.format_results(results))

        # Save raw results to ~/.config/redhat-source/
        safe_query = query.replace(' ', '_')[:50]
        output_file = CREDS_DIR / f"search_results_{safe_query}.json"
        CREDS_DIR.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"\n{'='*80}")
        print(f"Raw results saved to: {output_file}")
        print(f"{'='*80}")

    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
