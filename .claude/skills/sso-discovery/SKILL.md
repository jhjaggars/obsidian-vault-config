---
name: sso-authentication-discovery
description: Interactive discovery and configuration of SSO authentication for Red Hat internal services. Use this skill when users need to set up authentication for SSO-protected sites (source.redhat.com, Slack, Jira, etc.), discover reliable authentication elements, or configure login for their projects. The skill uses element-based waiting for fast, reliable authentication instead of arbitrary timeouts.
---

# SSO Authentication Discovery

## Overview

This skill provides interactive discovery and configuration of SSO authentication for Red Hat internal services. Instead of using unreliable network idle states or arbitrary timeouts, this skill helps identify specific DOM elements that prove authentication succeeded, enabling fast and reliable authentication.

## When to Use This Skill

Use this skill when users ask to:
- Set up SSO authentication for a Red Hat service
- Configure login for source.redhat.com, Slack, Jira, or other internal tools
- Find a reliable way to detect when authentication completes
- Improve slow or unreliable authentication in their projects
- Discover what element to wait for after SSO login

## Core Workflow

### Phase 1: Discovery (One-Time Setup)

Run the discovery process to identify the authentication element:

```bash
python3 .claude/skills/sso-discovery/scripts/redhat_sso_auth/discovery.py \
    <service-url> \
    --service-name <name>
```

**Discovery Process:**
1. Opens browser to the service URL
2. Waits for user to complete SSO authentication manually
3. Analyzes the authenticated page to find reliable indicators
4. Suggests element selectors with confidence scores
5. User selects the best selector
6. Tests the selector on the current page
7. Saves configuration to `~/.redhat-sso-auth/<service-name>.json`

**Example Selectors by Service:**
- **source.redhat.com**: `a[href*="/.profile/"]` (profile links)
- **Slack**: `[role="tree"]` (navigation sidebar)
- **Jira**: `.aui-header-primary .aui-nav` (main navigation)

### Phase 2: Authentication (Every Use)

Once discovered, authenticate using the configuration:

```python
import sys
from pathlib import Path

# Add library to path
sys.path.insert(0, str(Path('.claude/skills/sso-discovery/scripts')))

from redhat_sso_auth import SSOAuthenticator, load_config

# Load configuration
config = load_config("source")  # or "slack", "jira", etc.

# Authenticate with element-based waiting
auth = SSOAuthenticator(config)
credentials = auth.authenticate()

# Credentials now contain cookies, localStorage, sessionStorage, etc.
```

## Key Innovation: Element-Based Waiting

**Traditional Approach (Slow & Unreliable):**
```python
page.wait_for_url("https://example.com/**", timeout=300000)  # 5 min
page.wait_for_load_state('networkidle', timeout=30000)       # 30 sec
page.wait_for_timeout(2000)                                   # 2 sec arbitrary
# Minimum 32 seconds, often much longer
```

**Element-Based Approach (Fast & Reliable):**
```python
page.wait_for_url("https://example.com/**", timeout=120000)
page.wait_for_selector(
    config.auth_element_selector,  # e.g., "a[href*='/.profile/']"
    timeout=30000,
    state='visible'
)
# Returns immediately when element appears (typically 2-10 seconds)
```

## Interactive Discovery Session Example

```
$ python3 discovery.py https://source.redhat.com --service-name source

================================================================================
SSO AUTHENTICATION ELEMENT DISCOVERY
================================================================================

Service: source
URL: https://source.redhat.com

Opening https://source.redhat.com...

================================================================================
Please complete authentication in the browser window
================================================================================

Press Enter when you're logged in and on the homepage: <Enter>

⏳ Analyzing authenticated page...
✓ Page analyzed: The Source homepage

⏳ Generating selector suggestions...

✓ Found 3 potential authentication indicators:

1. a[href*="/.profile/"], a[href*="/profile"]
   → User profile links
   → Confidence: 95%
   → Profile links only exist when authenticated
   → Found 10 element(s)

2. button:has-text("logout"), button:has-text("sign out")
   → Logout/sign out button
   → Confidence: 90%
   → Logout button only appears for authenticated users
   → Found 1 element(s)

3. button:has-text("Messages"), a:has-text("Messages")
   → Messages/notifications button
   → Confidence: 85%
   → Personal messages require authentication
   → Found 1 element(s)

Which selector do you want to use? [1-3] or 'c' for custom: 1

Testing selector: a[href*="/.profile/"], a[href*="/profile"]
✓ Element found on current page
✓ Configuration saved to ~/.redhat-sso-auth/source.json

================================================================================
CONFIGURATION SAVED
================================================================================

You can now authenticate using:
  from redhat_sso_auth import SSOAuthenticator, load_config
  config = load_config('source')
  auth = SSOAuthenticator(config)
  credentials = auth.authenticate()
```

## Configuration Structure

Configurations are saved to `~/.redhat-sso-auth/<service-name>.json`:

```json
{
  "service_name": "source",
  "base_url": "https://source.redhat.com",
  "auth_element_selector": "a[href*='/.profile/']",
  "auth_element_description": "User profile link",
  "wait_timeout": 120000,
  "use_persistent_context": false,
  "browser_profile_dir": null,
  "credentials_file": ".credentials.json",
  "auth_state_file": ".auth_state.json"
}
```

## Using Discovered Configuration in Projects

After discovery, guide users to integrate the authentication into their projects:

### Option 1: Direct Library Usage

```python
import sys
from pathlib import Path

# Add SSO auth library to path
sys.path.insert(0, str(Path('.claude/skills/sso-discovery/scripts')))

from redhat_sso_auth import SSOAuthenticator, load_config

def login():
    config = load_config("source")
    if not config:
        raise Exception("Run discovery first: python3 discovery.py ...")

    auth = SSOAuthenticator(config)
    return auth.authenticate()

if __name__ == "__main__":
    credentials = login()
    print("Authenticated successfully!")
```

### Option 2: Copy Library to Project

If the user wants to bundle the library with their project:

```bash
# Copy the library
cp -r .claude/skills/sso-discovery/scripts/redhat_sso_auth <project-path>/

# Copy the config
mkdir -p <project-path>/.sso-config
cp ~/.redhat-sso-auth/<service-name>.json <project-path>/.sso-config/
```

## Multiple Services

The skill supports configuring multiple SSO services:

```bash
# Discover each service once
python3 discovery.py https://source.redhat.com --service-name source
python3 discovery.py https://redhat-internal.slack.com --service-name slack
python3 discovery.py https://jira.redhat.com --service-name jira

# Use in code
config = load_config("source")  # or "slack" or "jira"
```

## Common Authentication Elements

When helping users discover elements, look for:

1. **Profile/User Links**: `a[href*="/profile"]`, `a[href*="/.profile/"]`
   - High reliability
   - Only appear when logged in

2. **Logout Buttons**: `button:has-text("logout")`, `button:has-text("sign out")`
   - Very reliable
   - Definitively indicates authenticated state

3. **Personal Features**: Messages, notifications, bookmarks
   - Reliable for internal tools
   - Require authentication to access

4. **User Avatars**: `img[alt*="avatar"]`, `img[class*="avatar"]`
   - Common pattern
   - Usually unique to logged-in state

5. **Navigation Elements**: Main menus, sidebars that only appear when authenticated
   - Service-specific
   - Good fallback option

## Troubleshooting

### No Suggestions Found

If discovery returns no automatic suggestions:
1. Manually inspect the authenticated page in browser
2. Look for elements that only appear when logged in
3. Use browser DevTools to find CSS selectors
4. Enter custom selector when prompted

### Selector Not Reliable

If authentication fails intermittently:
1. Re-run discovery to find a more reliable element
2. Choose an element that appears early (not lazy-loaded)
3. Avoid elements with dynamic IDs or classes
4. Prefer structural elements over content-based selectors

### Service Already Configured

To reconfigure a service:
```bash
# Delete old config
rm ~/.redhat-sso-auth/<service-name>.json

# Run discovery again
python3 discovery.py <url> --service-name <name>
```

## Resources

### scripts/redhat_sso_auth/

The complete SSO authentication library:

- **discovery.py** - Interactive element discovery (run this first)
- **authenticator.py** - Core authentication with element-based waiting
- **config.py** - Configuration loading/saving
- **credentials.py** - Credential management
- **__init__.py** - Package exports

### Pre-configured Services

The following service has already been discovered and configured:

- **source.redhat.com** (`~/.redhat-sso-auth/source.json`)
  - Selector: `a[href*="/.profile/"]`
  - Description: User profile link
  - Ready to use immediately
