"""
Generic SSO Authentication Library for Red Hat Services.

Provides reusable authentication components for SSO-protected services.
"""

from .authenticator import SSOAuthenticator
from .config import AuthConfig, load_config, save_config, list_configs
from .credentials import Credentials, CredentialManager
from .discovery import discover_auth_element, ElementSuggestion

__version__ = "0.1.0"

__all__ = [
    "SSOAuthenticator",
    "AuthConfig",
    "load_config",
    "save_config",
    "list_configs",
    "Credentials",
    "CredentialManager",
    "discover_auth_element",
    "ElementSuggestion",
]
