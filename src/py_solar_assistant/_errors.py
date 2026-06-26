"""Shared error type and HTTP-error helper for the cloud and device clients."""

from __future__ import annotations

from ._url import safe_url


class SolarAssistantError(Exception):
    def __init__(self, status: int | None, message: str) -> None:
        prefix = f"API error {status}" if status is not None else "Invalid response"
        super().__init__(f"{prefix}: {message}")
        self.status = status


def http_error(method: str, url: str, status: int) -> SolarAssistantError:
    """Build an error for a non-200 response."""
    return SolarAssistantError(status, f"{method} {safe_url(url)}")
