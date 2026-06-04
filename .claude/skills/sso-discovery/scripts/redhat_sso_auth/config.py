#!/usr/bin/env python3
"""
Configuration management for SSO authentication.

Handles loading and saving authentication configurations for different services.
"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class AuthConfig:
    """Configuration for SSO authentication."""

    service_name: str
    base_url: str
    auth_element_selector: str
    auth_element_description: str
    wait_timeout: int = 120000  # Milliseconds
    use_persistent_context: bool = False
    browser_profile_dir: Optional[str] = None
    credentials_file: str = ".credentials.json"
    auth_state_file: str = ".auth_state.json"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AuthConfig":
        """Create from dictionary."""
        return cls(**data)


def get_config_dir() -> Path:
    """Get the configuration directory."""
    config_dir = Path.home() / ".redhat-sso-auth"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path(service_name: str) -> Path:
    """Get the configuration file path for a service."""
    return get_config_dir() / f"{service_name}.json"


def load_config(service_name: str) -> Optional[AuthConfig]:
    """
    Load configuration for a service.

    Args:
        service_name: Name of the service (e.g., "source", "slack")

    Returns:
        AuthConfig if exists, None otherwise
    """
    config_path = get_config_path(service_name)

    if not config_path.exists():
        return None

    with open(config_path) as f:
        data = json.load(f)

    return AuthConfig.from_dict(data)


def save_config(config: AuthConfig) -> None:
    """
    Save configuration for a service.

    Args:
        config: Configuration to save
    """
    config_path = get_config_path(config.service_name)

    with open(config_path, 'w') as f:
        json.dump(config.to_dict(), f, indent=2)

    print(f"Configuration saved to: {config_path}")


def list_configs() -> list[str]:
    """
    List all configured services.

    Returns:
        List of service names
    """
    config_dir = get_config_dir()
    return [f.stem for f in config_dir.glob("*.json")]


def delete_config(service_name: str) -> bool:
    """
    Delete configuration for a service.

    Args:
        service_name: Name of the service

    Returns:
        True if deleted, False if not found
    """
    config_path = get_config_path(service_name)

    if config_path.exists():
        config_path.unlink()
        return True

    return False


if __name__ == "__main__":
    """Example usage."""
    # Create example config
    config = AuthConfig(
        service_name="source",
        base_url="https://source.redhat.com",
        auth_element_selector="a[href*='/.profile/']",
        auth_element_description="User profile link"
    )

    print("Example configuration:")
    print(json.dumps(config.to_dict(), indent=2))

    # Save
    save_config(config)

    # Load
    loaded = load_config("source")
    print(f"\nLoaded config: {loaded}")

    # List
    print(f"\nConfigured services: {list_configs()}")
