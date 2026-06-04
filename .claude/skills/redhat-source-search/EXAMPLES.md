# Red Hat Source Search - Examples

This document provides detailed examples of using the Red Hat Source Search skill.

## Example 1: First-Time Authentication

### Scenario
You need to access source.redhat.com for the first time and extract authentication credentials.

### Steps

1. **Run the login script:**
   ```bash
   uv run .claude/skills/redhat-source-search/login.py
   ```

2. **What happens:**
   - Browser window opens to https://source.redhat.com
   - Site redirects to Red Hat SSO login page
   - Playwright Inspector window appears with "Resume" button

3. **Complete authentication:**
   - Enter your Red Hat credentials in the browser
   - Complete any 2FA if required
   - Wait for successful login and redirect to homepage

4. **Extract credentials:**
   - Click "Resume" button in Playwright Inspector
   - Script extracts cookies, tokens, and headers
   - Saves to `credentials.json` and `auth_state.json`

5. **Verify success:**
   ```
   Summary:
     - Cookies: 43
     - localStorage items: 0
     - sessionStorage items: 2
     - Auth headers captured: 0

     Cookie names:
       - iglooauth
       - igjwt
       - KEYCLOAK_IDENTITY
       ...

   SUCCESS! Credentials have been extracted and saved.
   ```

---

## Example 2: Searching for Documentation

### Scenario
You need to find Red Hat internal documentation about "service delivery".

### Prerequisites
- Credentials already extracted (credentials.json exists)

### Steps

1. **Run the search script:**
   ```bash
   uv run .claude/skills/redhat-source-search/search.py "service delivery"
   ```

2. **Review results:**
   ```
   Searching: service delivery
   API: /.api2/api/v1/communities/10/search/contentdetailed
   Limit: 20, Offset: 0

   Found 25 results

   ================================================================================

   1. Customer Enablement Program Office
      Type: page
      URL: https://source.redhat.com/departments/enablement/program_office/...
      Created by: Jordan Reyes
      Modified: 2024-04-17T08:59:27.12-04:00

   2. Knowledge Base Center of Excellence
      Type: space
      URL: https://source.redhat.com/departments/it/kb_center...
      Description: The Knowledge Base Center of Excellence focuses on...
      Created by: Igloo Webmaster
      Modified: 2025-11-10T17:28:28.547-05:00

   ... (more results)
   ```

3. **Check saved JSON:**
   ```bash
   cat search_results_service_delivery.json
   ```

---

## Example 3: Re-authenticating When Credentials Expire

### Scenario
Search returns authentication error - credentials have expired.

### Error Message
```
❌ Error: Authentication failed (status 401). Credentials may be expired.
Re-run: uv run .claude/skills/redhat-source-search/login.py
```

### Steps

1. **Delete old credentials:**
   ```bash
   rm credentials.json auth_state.json
   ```

2. **Re-authenticate:**
   ```bash
   uv run .claude/skills/redhat-source-search/login.py
   ```

3. **Retry search:**
   ```bash
   uv run .claude/skills/redhat-source-search/search.py "your query"
   ```

---

## Example 4: Searching for Specific Topics

### Scenario
Find resources about different Red Hat topics.

### Search Examples

**Find OpenShift documentation:**
```bash
uv run .claude/skills/redhat-source-search/search.py "openshift deployment"
```

**Find HR policies:**
```bash
uv run .claude/skills/redhat-source-search/search.py "vacation policy"
```

**Find team contacts:**
```bash
uv run .claude/skills/redhat-source-search/search.py "product management team"
```

**Find engineering guides:**
```bash
uv run .claude/skills/redhat-source-search/search.py "python development guidelines"
```

---

## Example 5: Working with Search Results Programmatically

### Scenario
Extract specific information from search results JSON.

### Python Script Example

```python
import json

# Load search results
with open('search_results_service_delivery.json') as f:
    results = json.load(f)

# Extract all URLs
urls = [item['href'] for item in results['results']]

# Filter by type
pages = [item for item in results['results'] if item['objectType'] == 'page']
wikis = [item for item in results['results'] if item['objectType'] == 'wikiArticle']

# Get recent results (modified in last 30 days)
from datetime import datetime, timedelta

recent_threshold = datetime.now() - timedelta(days=30)
recent = [
    item for item in results['results']
    if datetime.fromisoformat(item['modifiedDate'].replace('-04:00', '')) > recent_threshold
]

print(f"Found {len(urls)} total results")
print(f"  {len(pages)} pages")
print(f"  {len(wikis)} wiki articles")
print(f"  {len(recent)} modified in last 30 days")
```

---

## Example 6: Pagination for Large Result Sets

### Scenario
Get more than 20 results using pagination.

### Modify search.py

Edit the search script to support pagination:

```python
# Get first 50 results in batches of 20
all_results = []

for offset in [0, 20, 40]:
    results = searcher.search(query, limit=20, offset=offset)
    all_results.extend(results['results'])
    print(f"Fetched results {offset} to {offset + 20}")

print(f"Total results collected: {len(all_results)}")
```

---

## Example 7: Claude Code Workflow

### Scenario
Ask Claude to search Red Hat source for you.

### Conversation Example

**User:** "Search source.redhat.com for information about the employee referral program"

**Claude:** "I'll search source.redhat.com for information about the employee referral program. First, let me check if we have valid credentials."

```bash
# Claude checks for credentials.json
ls credentials.json
```

**Claude:** "Credentials exist. Running the search..."

```bash
uv run .claude/skills/redhat-source-search/search.py "employee referral program"
```

**Claude:** "Found 15 results about the employee referral program. Here are the top results:

1. **Employee Referral Program** (page)
   - URL: https://source.redhat.com/career/employee_referral_program
   - Created by: HR Team
   - This is the main page with program details and submission process

2. **Referral Bonus Policy** (wikiArticle)
   - Details on referral bonuses and eligibility

3. **How to Submit a Referral** (blogArticle)
   - Step-by-step guide for submitting referrals

The full results have been saved to `search_results_employee_referral_program.json`."

---

## Troubleshooting Examples

### Issue: Browser doesn't open

**Solution:**
```bash
# Verify Playwright is installed
uv run playwright install chromium

# Try again
uv run .claude/skills/redhat-source-search/login.py
```

### Issue: Network timeout

**Possible causes:**
- Not connected to Red Hat VPN
- Internal network required
- Firewall blocking connection

**Solution:**
1. Connect to Red Hat VPN
2. Verify network access:
   ```bash
   curl -I https://source.redhat.com
   ```

### Issue: Credentials not working

**Check credential age:**
```bash
cat credentials.json | grep extraction_timestamp
```

**If old, re-authenticate:**
```bash
rm credentials.json auth_state.json
uv run .claude/skills/redhat-source-search/login.py
```

---

## Advanced Usage

### Custom Search Script

Create a custom search script with filters:

```python
#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from search import SourceRedHatSearch

searcher = SourceRedHatSearch()
searcher.load_credentials()

# Search with custom parameters
results = searcher.search(
    query="documentation",
    limit=50,
    offset=0,
    detailed=True
)

# Filter results by type
wiki_articles = [
    r for r in results['results']
    if r['objectType'] == 'wikiArticle'
]

for article in wiki_articles[:10]:
    print(f"{article['title']}: {article['href']}")
```

---

## Tips and Best Practices

1. **Specific queries work better:** Use specific terms like "OpenShift deployment guide" instead of just "OpenShift"

2. **Check credentials regularly:** Credentials may expire after 24-48 hours of inactivity

3. **Save important results:** The JSON files contain full metadata - keep them for reference

4. **Use pagination for thorough searches:** Don't rely on just the first 20 results

5. **Verify VPN connection:** Always ensure VPN is connected before authentication

6. **Keep credentials secure:** The credentials.json file is gitignored - never commit it
