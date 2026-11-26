"""Auth service entrypoint. Product HTTP stays at /auth on this process."""

from auth.app import app

__all__ = ["app"]
