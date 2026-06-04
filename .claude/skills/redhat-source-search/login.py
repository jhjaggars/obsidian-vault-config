#!/usr/bin/env python3
# /// script
# dependencies = ["playwright>=1.55.0"]
# ///
"""
Red Hat SSO Authentication and Credential Extraction Script.

This script uses Playwright to:
1. Navigate to source.redhat.com
2. Allow manual SSO authentication
3. Extract authentication credentials (cookies, tokens, headers)
4. Save credentials for later programmatic use

Credentials are stored in ~/.config/redhat-source/ (never in the vault).
"""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

CREDS_DIR = Path.home() / ".config/redhat-source"


class RedHatAuthExtractor:
    """Handles authentication and credential extraction for Red Hat SSO."""

    def __init__(self, base_url: str = "https://source.redhat.com"):
        self.base_url = base_url
        CREDS_DIR.mkdir(parents=True, exist_ok=True)
        self.credentials_file = CREDS_DIR / "credentials.json"
        self.auth_state_file = CREDS_DIR / "auth_state.json"

    def extract_credentials(self, headless: bool = False, timeout: int = 60000) -> dict:
        """
        Launch browser, authenticate, and extract credentials.

        Args:
            headless: Whether to run browser in headless mode (default: False for manual auth)
            timeout: Navigation timeout in milliseconds (default: 60000)

        Returns:
            Dictionary containing extracted credentials
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            # Use a more permissive browser context to avoid redirect issues
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            print(f"Navigating to {self.base_url}...")
            print(f"Note: Site may redirect to login page - this is expected.")

            try:
                # Use networkidle instead of domcontentloaded to handle redirects better
                page.goto(self.base_url, timeout=timeout, wait_until="networkidle")
                print(f"✓ Loaded: {page.url}")
            except Exception as e:
                # Check if page loaded despite the error
                current_url = page.url
                if current_url and current_url != "about:blank":
                    print(f"⚠️  Navigation warning (but page loaded): {type(e).__name__}")
                    print(f"Current URL: {current_url}")
                else:
                    print(f"\n⚠️  Navigation error: {e}")
                    print("\nPossible issues:")
                    print("  1. Are you connected to Red Hat VPN?")
                    print("  2. Is source.redhat.com accessible from your network?")
                    print("  3. Do you need to be on Red Hat's internal network?")
                    print("\nThe browser window will stay open for manual navigation...")
                    print("Navigate to the site manually in the browser window.")

            print("\n" + "="*80)
            print("MANUAL AUTHENTICATION REQUIRED")
            print("="*80)
            print("Please complete the Red Hat SSO login in the browser window.")
            print("When finished, click the 'Resume' button in the Playwright Inspector.")
            print("="*80 + "\n")

            # Pause execution and wait for user to manually resume
            # This keeps the browser open indefinitely until user clicks "Resume"
            page.pause()

            print("Resumed! Checking authentication status...")

            # Wait for authentication to complete by detecting when we're back on source.redhat.com
            # and the page is fully loaded (not on auth.redhat.com)
            try:
                # Wait for navigation away from auth page and back to source.redhat.com
                print("Waiting for SSO authentication to complete...")
                page.wait_for_url("https://source.redhat.com/**", timeout=30000)  # 30 sec timeout after resume
                print("✓ Redirected back to source.redhat.com")

                # Wait for page to be fully loaded
                page.wait_for_load_state('networkidle', timeout=30000)
                print("✓ Page loaded successfully")
            except Exception as e:
                print(f"⚠️  Timeout or error waiting for authentication: {e}")
                print("Attempting to extract credentials anyway...")

            # Wait a moment for any final redirects or JS to complete
            page.wait_for_timeout(2000)

            print("\nExtracting credentials...")
            credentials = self._extract_all_credentials(page, context)

            # Save browser state for future use
            print("Saving browser authentication state...")
            context.storage_state(path=str(self.auth_state_file))

            browser.close()

            return credentials

    def _extract_all_credentials(self, page: Page, context: BrowserContext) -> dict:
        """Extract all available credentials from the authenticated session."""

        # Extract cookies
        cookies = context.cookies()

        # Extract localStorage (with error handling for navigation issues)
        local_storage = {}
        try:
            local_storage = page.evaluate("""() => {
                let items = {};
                for (let i = 0; i < localStorage.length; i++) {
                    let key = localStorage.key(i);
                    items[key] = localStorage.getItem(key);
                }
                return items;
            }""")
        except Exception as e:
            print(f"⚠️  Could not extract localStorage: {e}")

        # Extract sessionStorage (with error handling for navigation issues)
        session_storage = {}
        try:
            session_storage = page.evaluate("""() => {
                let items = {};
                for (let i = 0; i < sessionStorage.length; i++) {
                    let key = sessionStorage.key(i);
                    items[key] = sessionStorage.getItem(key);
                }
                return items;
            }""")
        except Exception as e:
            print(f"⚠️  Could not extract sessionStorage: {e}")

        # Capture some network requests to identify auth headers
        print("Monitoring network requests for authentication headers...")
        auth_headers = {}

        # Set up request listener
        def handle_request(request):
            headers = request.headers
            # Look for common auth header patterns
            for header_name in ['authorization', 'x-api-key', 'x-auth-token', 'x-csrf-token']:
                if header_name in headers:
                    auth_headers[header_name] = headers[header_name]

        page.on('request', handle_request)

        # Trigger some requests by navigating or interacting
        try:
            page.wait_for_load_state('networkidle', timeout=5000)
        except:
            pass  # Timeout is okay

        current_url = page.url

        # Get timestamp safely
        timestamp = None
        try:
            timestamp = str(page.evaluate("() => new Date().toISOString()"))
        except:
            from datetime import datetime
            timestamp = datetime.now().isoformat()

        credentials = {
            "base_url": self.base_url,
            "current_url": current_url,
            "cookies": cookies,
            "local_storage": local_storage,
            "session_storage": session_storage,
            "auth_headers": auth_headers,
            "extraction_timestamp": timestamp
        }

        return credentials

    def save_credentials(self, credentials: dict) -> None:
        """Save extracted credentials to a JSON file."""
        print(f"\nSaving credentials to {self.credentials_file}...")

        with open(self.credentials_file, 'w') as f:
            json.dump(credentials, f, indent=2)

        print(f"Credentials saved successfully!")
        print(f"\nSummary:")
        print(f"  - Cookies: {len(credentials['cookies'])}")
        print(f"  - localStorage items: {len(credentials['local_storage'])}")
        print(f"  - sessionStorage items: {len(credentials['session_storage'])}")
        print(f"  - Auth headers captured: {len(credentials['auth_headers'])}")

        # Show cookie names (not values for security)
        if credentials['cookies']:
            print(f"\n  Cookie names:")
            for cookie in credentials['cookies']:
                print(f"    - {cookie['name']}")

        if credentials['auth_headers']:
            print(f"\n  Auth headers found:")
            for header in credentials['auth_headers']:
                print(f"    - {header}")

    def load_credentials(self) -> dict:
        """Load previously saved credentials."""
        if not self.credentials_file.exists():
            raise FileNotFoundError(
                f"Credentials file not found: {self.credentials_file}\n"
                "Run the extraction script first to authenticate and save credentials."
            )

        with open(self.credentials_file, 'r') as f:
            return json.load(f)


def main():
    """Main execution function."""
    print("Red Hat SSO Credential Extractor")
    print("=" * 80)

    extractor = RedHatAuthExtractor()

    try:
        # Extract credentials (browser will open for manual auth)
        credentials = extractor.extract_credentials(headless=False)

        # Save to file
        extractor.save_credentials(credentials)

        print("\n" + "="*80)
        print("SUCCESS! Credentials have been extracted and saved.")
        print("="*80)
        print(f"\nYou can now use these credentials in other scripts by loading")
        print(f"the '{extractor.credentials_file}' file.")
        print(f"\nThe browser state has also been saved to '{extractor.auth_state_file}'")
        print("which can be used to restore the authenticated session in Playwright.")

    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
