#!/usr/bin/env python3
"""
Interactive discovery of authentication elements.

Helps users identify reliable elements that indicate successful authentication.
Uses LLM assistance to suggest good selectors.
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from playwright.sync_api import sync_playwright, Page

from .config import AuthConfig, save_config

logger = logging.getLogger(__name__)


@dataclass
class ElementSuggestion:
    """Suggested element selector."""

    selector: str
    description: str
    confidence: float
    reasoning: str
    element_count: int = 0


def capture_page_state(page: Page) -> dict:
    """
    Capture authenticated page state for analysis.

    Args:
        page: Playwright page

    Returns:
        Dictionary with page analysis data
    """
    # Get accessibility snapshot
    snapshot = page.accessibility.snapshot()

    # Find common authentication indicators
    indicators = page.evaluate("""() => {
        const indicators = [];

        // Profile links
        const profileLinks = document.querySelectorAll('a[href*="/profile"], a[href*="/.profile/"]');
        if (profileLinks.length > 0) {
            indicators.push({
                type: 'profile-link',
                selector: 'a[href*="/.profile/"], a[href*="/profile"]',
                count: profileLinks.length,
                sampleText: profileLinks[0]?.textContent?.trim(),
                sampleHref: profileLinks[0]?.href
            });
        }

        // User menu/dropdown
        const userButtons = Array.from(document.querySelectorAll('button, a')).filter(el =>
            el.textContent?.toLowerCase().includes('logout') ||
            el.textContent?.toLowerCase().includes('sign out') ||
            el.textContent?.toLowerCase().includes('profile') ||
            el.getAttribute('aria-label')?.toLowerCase().includes('user') ||
            el.getAttribute('aria-label')?.toLowerCase().includes('account')
        );
        if (userButtons.length > 0) {
            indicators.push({
                type: 'user-menu',
                count: userButtons.length,
                sampleText: userButtons[0]?.textContent?.trim(),
                sampleClass: userButtons[0]?.className
            });
        }

        // Messages/notifications (common in internal tools)
        const messageButtons = Array.from(document.querySelectorAll('button, a')).filter(el =>
            el.textContent?.toLowerCase().includes('message') ||
            el.textContent?.toLowerCase().includes('notification') ||
            el.getAttribute('aria-label')?.toLowerCase().includes('message')
        );
        if (messageButtons.length > 0) {
            indicators.push({
                type: 'messages',
                count: messageButtons.length,
                sampleText: messageButtons[0]?.textContent?.trim()
            });
        }

        // Avatar images (often unique to logged-in state)
        const avatars = document.querySelectorAll('img[alt*="avatar"], img[alt*="profile"], img[class*="avatar"]');
        if (avatars.length > 0) {
            indicators.push({
                type: 'avatar',
                count: avatars.length,
                sampleAlt: avatars[0]?.alt
            });
        }

        return indicators;
    }""")

    return {
        "url": page.url,
        "title": page.title(),
        "accessibility_tree": snapshot,
        "indicators": indicators
    }


def suggest_selectors_with_llm(page_state: dict, llm_prompt_fn: Optional[callable] = None) -> List[ElementSuggestion]:
    """
    Use LLM to suggest reliable authentication element selectors.

    Args:
        page_state: Captured page state
        llm_prompt_fn: Optional function to call LLM

    Returns:
        List of element suggestions
    """
    suggestions = []

    # Build suggestions from indicators
    for indicator in page_state.get("indicators", []):
        if indicator["type"] == "profile-link" and indicator["count"] > 0:
            suggestions.append(ElementSuggestion(
                selector='a[href*="/.profile/"], a[href*="/profile"]',
                description="User profile links",
                confidence=0.95,
                reasoning="Profile links only exist when authenticated",
                element_count=indicator["count"]
            ))

        elif indicator["type"] == "user-menu" and indicator["count"] > 0:
            suggestions.append(ElementSuggestion(
                selector='button:has-text("logout"), button:has-text("sign out")',
                description="Logout/sign out button",
                confidence=0.90,
                reasoning="Logout button only appears for authenticated users",
                element_count=indicator["count"]
            ))

        elif indicator["type"] == "messages" and indicator["count"] > 0:
            suggestions.append(ElementSuggestion(
                selector='button:has-text("Messages"), a:has-text("Messages")',
                description="Messages/notifications button",
                confidence=0.85,
                reasoning="Personal messages require authentication",
                element_count=indicator["count"]
            ))

        elif indicator["type"] == "avatar" and indicator["count"] > 0:
            suggestions.append(ElementSuggestion(
                selector='img[alt*="avatar"], img[class*="avatar"]',
                description="User avatar image",
                confidence=0.80,
                reasoning="User avatar typically only shows when logged in",
                element_count=indicator["count"]
            ))

    # If LLM function provided, get additional suggestions
    if llm_prompt_fn:
        try:
            llm_suggestions = llm_prompt_fn(page_state)
            suggestions.extend(llm_suggestions)
        except Exception as e:
            logger.warning(f"LLM suggestion failed: {e}")

    # Sort by confidence
    suggestions.sort(key=lambda x: x.confidence, reverse=True)

    return suggestions


def discover_auth_element(
    base_url: str,
    service_name: str,
    llm_prompt_fn: Optional[callable] = None
) -> AuthConfig:
    """
    Interactive discovery of authentication element.

    Args:
        base_url: URL to authenticate to
        service_name: Name for this service configuration
        llm_prompt_fn: Optional LLM function for suggestions

    Returns:
        Configured AuthConfig
    """
    print("="*80)
    print("SSO AUTHENTICATION ELEMENT DISCOVERY")
    print("="*80)
    print()
    print(f"Service: {service_name}")
    print(f"URL: {base_url}")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = context.new_page()

        try:
            # Navigate to service
            print(f"Opening {base_url}...")
            page.goto(base_url, wait_until="domcontentloaded", timeout=60000)

            # Wait for user to authenticate
            print("\n" + "="*80)
            print("Please complete authentication in the browser window")
            print("="*80)
            input("\nPress Enter when you're logged in and on the homepage: ")

            # Capture authenticated page state
            print("\n⏳ Analyzing authenticated page...")
            page_state = capture_page_state(page)
            print(f"✓ Page analyzed: {page_state['title']}")

            # Get suggestions
            print("\n⏳ Generating selector suggestions...")
            suggestions = suggest_selectors_with_llm(page_state, llm_prompt_fn)

            if not suggestions:
                print("\n❌ No automatic suggestions found.")
                print("You'll need to manually provide a selector.")
                selector = input("\nEnter CSS selector for auth element: ")
                description = input("Describe what this element is: ")

                return AuthConfig(
                    service_name=service_name,
                    base_url=base_url,
                    auth_element_selector=selector,
                    auth_element_description=description
                )

            # Display suggestions
            print(f"\n✓ Found {len(suggestions)} potential authentication indicators:\n")

            for i, suggestion in enumerate(suggestions[:5], 1):
                print(f"{i}. {suggestion.selector}")
                print(f"   → {suggestion.description}")
                print(f"   → Confidence: {suggestion.confidence:.0%}")
                print(f"   → {suggestion.reasoning}")
                print(f"   → Found {suggestion.element_count} element(s)")
                print()

            # Let user choose
            while True:
                choice = input(f"Which selector do you want to use? [1-{len(suggestions[:5])}] or 'c' for custom: ")

                if choice.lower() == 'c':
                    selector = input("\nEnter CSS selector: ")
                    description = input("Describe what this element is: ")
                    break
                else:
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(suggestions[:5]):
                            selected = suggestions[idx]
                            selector = selected.selector
                            description = selected.description
                            break
                    except ValueError:
                        pass

                print("Invalid choice, try again.")

            # Test selector on current page
            print(f"\nTesting selector: {selector}")
            try:
                element = page.wait_for_selector(selector, timeout=5000, state='visible')
                if element:
                    print("✓ Element found on current page")
                else:
                    print("⚠️  Element not found - this may not work reliably")
            except Exception as e:
                print(f"⚠️  Error testing selector: {e}")
                print("   Proceeding anyway - you may need to adjust later")

            # Create config
            config = AuthConfig(
                service_name=service_name,
                base_url=base_url,
                auth_element_selector=selector,
                auth_element_description=description
            )

            # Save config
            save_config(config)

            print("\n" + "="*80)
            print("CONFIGURATION SAVED")
            print("="*80)
            print(f"\nYou can now authenticate using:")
            print(f"  from redhat_sso_auth import SSOAuthenticator, load_config")
            print(f"  config = load_config('{service_name}')")
            print(f"  auth = SSOAuthenticator(config)")
            print(f"  credentials = auth.authenticate()")

            return config

        finally:
            browser.close()


if __name__ == "__main__":
    """CLI for discovery."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Discover authentication element for SSO service"
    )
    parser.add_argument("url", help="Base URL of the service")
    parser.add_argument("--service-name", required=True, help="Name for this service")

    args = parser.parse_args()

    config = discover_auth_element(args.url, args.service_name)
    print(f"\n✓ Configuration saved for service: {config.service_name}")
