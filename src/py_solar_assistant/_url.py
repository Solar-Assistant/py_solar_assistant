"""URL hygiene helpers shared by the cloud and device clients."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def safe_url(url: str) -> str:
    """Return ``url`` with any ``user:pass@`` userinfo stripped."""
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))
