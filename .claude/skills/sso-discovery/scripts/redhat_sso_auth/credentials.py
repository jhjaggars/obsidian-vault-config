#!/usr/bin/env python3
"""
Credential management for SSO authentication.

Handles storage, loading, and validation of authentication credentials.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any


@dataclass
class Credentials:
    """Authentication credentials."""

    service_name: str
    cookies: List[Dict[str, Any]]
    local_storage: Dict[str, str]
    session_storage: Dict[str, str]
    auth_headers: Dict[str, str]
    timestamp: str
    base_url: str
    current_url: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Credentials":
        """Create from dictionary."""
        return cls(**data)

    def age_hours(self) -> float:
        """Get age of credentials in hours."""
        created = datetime.fromisoformat(self.timestamp)
        now = datetime.now()
        delta = now - created
        return delta.total_seconds() / 3600


class CredentialManager:
    """Manage authentication credentials."""

    def __init__(self, credentials_dir: Optional[Path] = None):
        """
        Initialize credential manager.

        Args:
            credentials_dir: Directory to store credentials.
                           Defaults to current directory.
        """
        self.credentials_dir = credentials_dir or Path.cwd()

    def get_credentials_path(self, service_name: str, filename: str = ".credentials.json") -> Path:
        """Get path to credentials file."""
        return self.credentials_dir / f".{service_name}-credentials.json"

    def get_auth_state_path(self, service_name: str) -> Path:
        """Get path to auth state file."""
        return self.credentials_dir / f".{service_name}-auth_state.json"

    def save(self, credentials: Credentials) -> None:
        """
        Save credentials to file.

        Args:
            credentials: Credentials to save
        """
        creds_path = self.get_credentials_path(credentials.service_name)

        with open(creds_path, 'w') as f:
            json.dump(credentials.to_dict(), f, indent=2)

        print(f"✓ Credentials saved to: {creds_path}")
        print(f"  - Cookies: {len(credentials.cookies)}")
        print(f"  - localStorage items: {len(credentials.local_storage)}")
        print(f"  - sessionStorage items: {len(credentials.session_storage)}")
        print(f"  - Auth headers: {len(credentials.auth_headers)}")

    def load(self, service_name: str) -> Optional[Credentials]:
        """
        Load credentials for a service.

        Args:
            service_name: Name of the service

        Returns:
            Credentials if found, None otherwise
        """
        creds_path = self.get_credentials_path(service_name)

        if not creds_path.exists():
            return None

        with open(creds_path) as f:
            data = json.load(f)

        return Credentials.from_dict(data)

    def is_valid(self, credentials: Credentials, max_age_hours: int = 24) -> bool:
        """
        Check if credentials are still valid.

        Args:
            credentials: Credentials to check
            max_age_hours: Maximum age in hours

        Returns:
            True if credentials appear valid
        """
        # Check age
        age = credentials.age_hours()
        if age > max_age_hours:
            return False

        # Check that we have essential data
        if not credentials.cookies:
            return False

        return True

    def delete(self, service_name: str) -> bool:
        """
        Delete credentials for a service.

        Args:
            service_name: Name of the service

        Returns:
            True if deleted, False if not found
        """
        creds_path = self.get_credentials_path(service_name)
        auth_state_path = self.get_auth_state_path(service_name)

        deleted = False

        if creds_path.exists():
            creds_path.unlink()
            deleted = True

        if auth_state_path.exists():
            auth_state_path.unlink()
            deleted = True

        return deleted

    def list_services(self) -> List[str]:
        """
        List all services with saved credentials.

        Returns:
            List of service names
        """
        pattern = ".*-credentials.json"
        files = self.credentials_dir.glob(pattern)
        return [f.stem.replace("-credentials", "") for f in files if f.name.startswith(".")]


if __name__ == "__main__":
    """Example usage."""
    from datetime import datetime

    # Create example credentials
    creds = Credentials(
        service_name="source",
        cookies=[{"name": "test", "value": "123"}],
        local_storage={},
        session_storage={},
        auth_headers={},
        timestamp=datetime.now().isoformat(),
        base_url="https://source.redhat.com",
        current_url="https://source.redhat.com/"
    )

    # Create manager
    manager = CredentialManager()

    # Save
    manager.save(creds)

    # Load
    loaded = manager.load("source")
    print(f"\nLoaded credentials: {loaded.service_name}")
    print(f"Age: {loaded.age_hours():.2f} hours")
    print(f"Valid: {manager.is_valid(loaded)}")

    # List
    print(f"\nServices with credentials: {manager.list_services()}")

    # Cleanup
    manager.delete("source")
