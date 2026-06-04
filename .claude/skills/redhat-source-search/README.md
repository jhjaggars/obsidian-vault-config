# Red Hat Source Search Skill

A Claude Code skill for authenticating to Red Hat's internal source.redhat.com intranet and searching for documentation, pages, wikis, and resources programmatically.

## Overview

This skill provides two main capabilities:

1. **Authentication** - Extract Red Hat SSO credentials via Playwright browser automation
2. **Search** - Programmatically search source.redhat.com using the internal API

## Quick Start

### Prerequisites

- Python 3.12+
- `uv` package manager
- Red Hat SSO account
- Access to source.redhat.com (may require VPN)

### Installation

Dependencies are managed via the project's `pyproject.toml`:

```toml
[project.dependencies]
playwright = ">=1.55.0"
httpx = ">=0.28.1"
python-dotenv = ">=1.2.1"
```

Install Playwright browsers:

```bash
uv run playwright install chromium
```

### First Time Setup

1. **Authenticate and extract credentials:**
   ```bash
   uv run .claude/skills/redhat-source-search/login.py
   ```

2. **Complete Red Hat SSO login in the browser**

3. **Click "Resume" in Playwright Inspector**

4. **Credentials saved to:**
   - `credentials.json` - Authentication cookies and tokens
   - `auth_state.json` - Playwright browser state

### Searching

```bash
uv run .claude/skills/redhat-source-search/search.py "your search query"
```

Example:
```bash
uv run .claude/skills/redhat-source-search/search.py "service delivery"
```

## Files

- **SKILL.md** - Skill definition and instructions for Claude
- **login.py** - Standalone authentication script
- **search.py** - Standalone search script
- **EXAMPLES.md** - Detailed usage examples
- **README.md** - This file

## How It Works

### Authentication Flow

1. Playwright launches Chromium browser
2. Navigates to https://source.redhat.com
3. Site redirects to Red Hat SSO (Keycloak)
4. User completes manual authentication
5. Script extracts:
   - **Cookies**: Session cookies including `iglooauth`, `igjwt`, `KEYCLOAK_IDENTITY`
   - **localStorage**: Browser local storage items
   - **sessionStorage**: Browser session storage items
   - **Headers**: Any authentication headers from network requests

6. Credentials saved to JSON files for reuse

### Search Flow

1. Load credentials from `credentials.json`
2. Build HTTP request with cookies and headers
3. Call search API endpoint
4. Parse and format results
5. Save raw JSON response

## API Endpoints Discovered

Through network traffic analysis, we identified the internal search API:

### Detailed Search (Recommended)
```
GET /.api2/api/v1/communities/10/search/contentdetailed
```

**Parameters:**
- `query` - Search query string
- `limit` - Number of results (default: 20)
- `offset` - Pagination offset (default: 0)
- `includeMicroblog` - Include microblog posts (default: true)
- `includeArchived` - Include archived content (default: false)
- `facetFields` - Facet filter ID (default: 92)

**Response Structure:**
```json
{
  "fusionQueryId": "...",
  "results": [
    {
      "id": "...",
      "objectType": "page|wikiArticle|blogArticle|space",
      "title": "...",
      "href": "/path/to/resource",
      "description": "...",
      "createdById": "...",
      "createdByFullName": "...",
      "modifiedDate": "2025-11-10T17:28:28.547-05:00",
      "content": "...",
      "contentFull": "..."
    }
  ]
}
```

### Simple Search (Alternative)
```
GET /.api2/api/v1/communities/10/search/content
```

**Parameters:**
- `query` - Search query string
- `limit` - Number of results
- `offset` - Pagination offset
- `parentHref` - Parent path filter (default: empty)

## Credential Management

### Security Notes

- Credentials are stored in `credentials.json` and `auth_state.json`
- These files are **gitignored** and should never be committed
- Contains sensitive authentication tokens - keep secure
- Credentials may expire after 24-48 hours

### Important Cookies

The authentication relies on several key cookies:

- **iglooauth** - Main authentication cookie for source.redhat.com
- **igjwt** - JWT token for API requests
- **KEYCLOAK_IDENTITY** - Red Hat SSO identity token
- **KEYCLOAK_SESSION** - SSO session cookie
- **AUTH_SESSION_ID** - Authentication session identifier

### Credential Expiration

If you receive authentication errors:

1. Delete old credentials:
   ```bash
   rm credentials.json auth_state.json
   ```

2. Re-authenticate:
   ```bash
   uv run .claude/skills/redhat-source-search/login.py
   ```

## Search Result Types

The API returns various content types:

- **page** - Standard page content
- **wikiArticle** - Wiki article/documentation
- **blogArticle** - Blog post
- **space** - Community space or group
- **microblog** - Short-form posts (if enabled)

## Troubleshooting

### Browser Won't Open

**Issue:** Playwright browser fails to launch

**Solution:**
```bash
uv run playwright install chromium
```

### Network Timeout

**Issue:** Connection timeout to source.redhat.com

**Possible Causes:**
- Not connected to Red Hat VPN
- Site requires internal network access
- Firewall blocking connection

**Solution:**
1. Verify VPN connection
2. Test connectivity:
   ```bash
   curl -I https://source.redhat.com
   ```

### Authentication Fails

**Issue:** Login completes but credentials don't work

**Solutions:**
1. Ensure you fully completed SSO authentication
2. Try with a fresh browser (delete `auth_state.json`)
3. Check for any 2FA requirements
4. Verify your Red Hat account has access to source.redhat.com

### Search Returns No Results

**Issue:** API returns empty or no results

**Possible Causes:**
- Credentials expired
- Query too broad or specific
- Content type filtering

**Solutions:**
1. Re-authenticate if credentials are old
2. Try more specific search terms
3. Test the same query on the website manually

## Advanced Usage

### Custom Search Parameters

Modify `search.py` to use custom parameters:

```python
results = searcher.search(
    query="documentation",
    limit=50,        # More results
    offset=20,       # Skip first 20
    detailed=True    # Use detailed endpoint
)
```

### Filtering Results

```python
import json

with open('search_results_query.json') as f:
    results = json.load(f)

# Filter by type
wiki_articles = [
    r for r in results['results']
    if r['objectType'] == 'wikiArticle'
]

# Filter by date
from datetime import datetime, timedelta
recent = [
    r for r in results['results']
    if datetime.fromisoformat(r['modifiedDate'].replace('-04:00', ''))
       > datetime.now() - timedelta(days=30)
]
```

### Pagination

```python
all_results = []
for offset in range(0, 100, 20):  # Get 100 results
    results = searcher.search(query, limit=20, offset=offset)
    all_results.extend(results['results'])
```

## Network Traffic Analysis

This skill was built by monitoring network requests during manual searches. Key findings:

1. **Search is client-side initiated** - JavaScript triggers XHR requests
2. **Community ID is hardcoded** - Community "10" represents the main workspace
3. **Cookies are sufficient** - No special API keys needed beyond cookies
4. **Pagination is offset-based** - Standard limit/offset pagination
5. **Multiple endpoints available** - Both simple and detailed search APIs

## Contributing

This is a project skill - it can be shared with your team via git.

To modify:
1. Edit scripts in `.claude/skills/redhat-source-search/`
2. Update SKILL.md if changing behavior
3. Add examples to EXAMPLES.md
4. Test with your own credentials
5. Commit changes (never commit credentials.json!)

## License

Internal Red Hat tool - use in accordance with Red Hat policies.

## Related Documentation

- [Playwright Documentation](https://playwright.dev/python/)
- [httpx Documentation](https://www.python-httpx.org/)
- [Red Hat SSO/Keycloak](https://www.keycloak.org/)
- source.redhat.com (requires authentication)

## Support

For issues:
1. Check EXAMPLES.md for common scenarios
2. Verify credentials are current
3. Test connectivity to source.redhat.com
4. Re-run authentication if needed

## Changelog

### Version 1.0.0 (2025-11-11)
- Initial release
- Playwright-based authentication
- API search implementation
- Support for detailed and simple search endpoints
- Credential management
- Comprehensive documentation
