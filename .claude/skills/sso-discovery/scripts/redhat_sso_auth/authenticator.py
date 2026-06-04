#!/usr/bin/env python3
"""
Generic SSO authenticator with element-based waiting.

This is the core authentication logic extracted from service-specific implementations.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

from .config import AuthConfig
from .credentials import Credentials, CredentialManager

logger = logging.getLogger(__name__)


class SSOAuthenticator:
    """Generic SSO authenticator using element-based waiting."""

    def __init__(self, config: AuthConfig, credentials_manager: Optional[CredentialManager] = None):
        """
        Initialize authenticator.

        Args:
            config: Authentication configuration
            credentials_manager: Optional credential manager
        """
        self.config = config
        self.credentials_manager = credentials_manager or CredentialManager()

    def authenticate(self, headless: bool = False) -> Credentials:
        """
        Perform SSO authentication with element-based waiting.

        This is the key improvement: instead of arbitrary timeouts,
        we wait for a specific element that proves authentication succeeded.

        Args:
            headless: Run browser in headless mode

        Returns:
            Extracted credentials
        """
        print(f"Authenticating to: {self.config.base_url}")
        print(f"Service: {self.config.service_name}")
        print()

        with sync_playwright() as p:
            if self.config.use_persistent_context and self.config.browser_profile_dir:
                # Use persistent context (stays logged in)
                context = p.chromium.launch_persistent_context(
                    user_data_dir=self.config.browser_profile_dir,
                    headless=headless,
                    viewport={'width': 1280, 'height': 720}
                )
                page = context.pages[0] if context.pages else context.new_page()
            else:
                # Use ephemeral context
                browser = p.chromium.launch(headless=headless)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                )
                page = context.new_page()

            try:
                # Navigate to service
                print(f"Opening {self.config.base_url}...")
                page.goto(self.config.base_url, wait_until="networkidle", timeout=60000)
                print(f"✓ Loaded: {page.url}")

                # Wait for authentication
                authenticated = self._wait_for_authentication(page)

                if not authenticated:
                    raise Exception("Authentication failed or timed out")

                print("✓ Authentication verified")

                # Extract credentials
                print("\nExtracting credentials...")
                credentials = self._extract_credentials(page, context)

                # Save browser state if not using persistent context
                if not self.config.use_persistent_context:
                    auth_state_path = self.credentials_manager.get_auth_state_path(
                        self.config.service_name
                    )
                    print(f"Saving browser state to: {auth_state_path}")
                    context.storage_state(path=str(auth_state_path))

                # Save credentials
                self.credentials_manager.save(credentials)

                print("\n" + "="*80)
                print("SUCCESS! Authentication complete")
                print("="*80)

                return credentials

            finally:
                context.close()
                if not self.config.use_persistent_context:
                    browser.close()

    def _wait_for_authentication(self, page: Page) -> bool:
        """
        Wait for authentication to complete using element-based waiting.

        This is the KEY IMPROVEMENT over arbitrary timeouts:
        - Waits for specific element that proves auth succeeded
        - Returns immediately when element appears
        - Reliable and deterministic

        Args:
            page: Playwright page

        Returns:
            True if authenticated successfully
        """
        print("\n" + "="*80)
        print("AUTHENTICATION REQUIRED")
        print("="*80)
        print("Please complete SSO login in the browser window.")
        print(f"Waiting for: {self.config.auth_element_description}")
        print("="*80 + "\n")

        try:
            # Wait for URL to contain base domain (in case of redirects)
            from urllib.parse import urlparse
            base_domain = urlparse(self.config.base_url).netloc

            # First wait for redirect back from SSO
            print("⏳ Waiting for SSO redirect...")
            page.wait_for_url(f"**{base_domain}/**", timeout=self.config.wait_timeout)
            print(f"✓ Redirected back to {base_domain}")

            # NOW THE KEY PART: Wait for element that proves authentication
            print(f"⏳ Waiting for authentication indicator: {self.config.auth_element_description}")
            print(f"   Selector: {self.config.auth_element_selector}")

            page.wait_for_selector(
                self.config.auth_element_selector,
                timeout=30000,  # 30 seconds should be enough once we're on the right page
                state='visible'
            )

            print(f"✓ Found: {self.config.auth_element_description}")
            return True

        except Exception as e:
            print(f"❌ Authentication timeout or error: {e}")
            return False

    def _extract_credentials(self, page: Page, context: BrowserContext) -> Credentials:
        """
        Extract credentials from authenticated session.

        Args:
            page: Playwright page
            context: Browser context

        Returns:
            Extracted credentials
        """
        # Extract cookies
        cookies = context.cookies()

        # Extract localStorage
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
            logger.warning(f"Could not extract localStorage: {e}")

        # Extract sessionStorage
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
            logger.warning(f"Could not extract sessionStorage: {e}")

        # Monitor for auth headers (brief monitoring)
        auth_headers = {}

        def handle_request(request):
            headers = request.headers
            for header_name in ['authorization', 'x-api-key', 'x-auth-token', 'x-csrf-token']:
                if header_name in headers:
                    auth_headers[header_name] = headers[header_name]

        page.on('request', handle_request)

        try:
            page.wait_for_load_state('networkidle', timeout=5000)
        except:
            pass  # Timeout is okay

        # Get current state
        current_url = page.url
        timestamp = datetime.now().isoformat()

        return Credentials(
            service_name=self.config.service_name,
            cookies=cookies,
            local_storage=local_storage,
            session_storage=session_storage,
            auth_headers=auth_headers,
            timestamp=timestamp,
            base_url=self.config.base_url,
            current_url=current_url
        )


if __name__ == "__main__":
    """Example usage."""
    from .config import AuthConfig

    # Example config
    config = AuthConfig(
        service_name="source",
        base_url="https://source.redhat.com",
        auth_element_selector="a[href*='/.profile/']",
        auth_element_description="User profile link"
    )

    # Authenticate
    auth = SSOAuthenticator(config)
    credentials = auth.authenticate()

    print(f"\nAuthenticated to {credentials.service_name}")
    print(f"Credentials age: {credentials.age_hours():.2f} hours")
