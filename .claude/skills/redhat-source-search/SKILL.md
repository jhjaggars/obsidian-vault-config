---
name: Red Hat Source Search
description: Authenticate to Red Hat's internal source.redhat.com intranet via SSO and search for documentation, pages, wikis, and resources. Use this skill when the user needs to login to source.redhat.com, extract credentials, or search for Red Hat internal documentation and resources.
---

# Red Hat Source Search

This skill provides authenticated access to Red Hat's internal source.redhat.com intranet, enabling credential extraction via Red Hat SSO and programmatic searching of internal resources.

## When to Use This Skill

Use this skill when the user asks to:
- Login to source.redhat.com
- Authenticate with Red Hat SSO
- Extract or update authentication credentials
- Search for Red Hat internal documentation
- Find pages, wikis, or resources on source.redhat.com
- Access the Red Hat intranet programmatically

## Workflow

### Initial Authentication (First Time or Expired Credentials)

1. Run the login script to authenticate:
   ```bash
   uv run .claude/skills/redhat-source-search/login.py
   ```

2. The script will:
   - Launch a browser window to source.redhat.com
   - Wait for manual Red Hat SSO authentication
   - Open Playwright Inspector with a "Resume" button
   - Extract credentials after authentication

3. User must:
   - Complete Red Hat SSO login in the browser
   - Click "Resume" in the Playwright Inspector when done

4. Credentials saved to:
   - `credentials.json` - Cookies, tokens, headers
   - `auth_state.json` - Playwright browser state

### Searching source.redhat.com

1. Ensure credentials exist (run login if needed)

2. Search using the search script:
   ```bash
   uv run .claude/skills/redhat-source-search/search.py "your query"
   ```

3. Results include:
   - Title, type, and URL of each result
   - Descriptions and metadata
   - Creator and modification dates
   - Raw JSON saved to file

## Important Notes

### Credentials Management
- Credentials are saved to `credentials.json` and `auth_state.json` in the project root
- These files are gitignored for security
- Credentials may expire - re-run login script if search fails with auth errors
- Session cookies include: `iglooauth`, `igjwt`, `KEYCLOAK_IDENTITY`

### Dependencies
- Requires `playwright` (for browser automation)
- Requires `httpx` (for HTTP requests)
- Managed via `uv` package manager

### API Details
- Search endpoint: `/.api2/api/v1/communities/10/search/contentdetailed`
- Supports pagination with `limit` and `offset` parameters
- Returns structured JSON with titles, URLs, descriptions, dates

## Error Handling

### Browser Timeout
If the browser fails to open or times out:
- Ensure you're connected to Red Hat VPN (if required)
- Check network connectivity
- Try increasing timeout in the script

### Authentication Failure
If credentials don't work:
- Delete `credentials.json` and `auth_state.json`
- Re-run login script
- Ensure you complete SSO authentication fully

### Search Returns Empty
If search returns no results:
- Verify credentials are valid (run login if needed)
- Check that the query is specific enough
- Try searching on the website manually first

## Best Practices

1. **Always check credentials first**: Before searching, verify `credentials.json` exists
2. **Re-authenticate proactively**: If credentials are old, re-run login before important searches
3. **Save search results**: Use the JSON output files for further processing
4. **Specific queries**: Use specific search terms for better results
5. **Pagination**: Use `limit` and `offset` for large result sets

## Examples

See EXAMPLES.md for detailed usage examples and workflows.
