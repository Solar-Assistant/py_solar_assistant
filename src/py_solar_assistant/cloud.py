"""SolarAssistant cloud API client — authentication, sites, and authorization."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any

import aiohttp

DEFAULT_BASE_URL = "https://solar-assistant.io"
_TIMEOUT = aiohttp.ClientTimeout(total=10)
_PAGINATION_KEYS = ("limit", "offset")

_SITES_PATH = "/api/v1/sites"
_AUTHORIZE_PATH = "/api/v1/sites/{site_id}/authorize"


class SolarAssistantError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"API error {status}: {message.strip()}")
        self.status = status


class SolarAssistantClient:
    """Authenticated client for the SolarAssistant cloud API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        verbose: bool = False,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.verbose = verbose
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "SolarAssistantClient":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def get(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        """GET <path> with optional filter params.

        Pagination keys (limit, offset) are sent as top-level query params.
        All other keys are joined as key:value and sent as a single ?q= param.
        """
        q: dict[str, str] = {}
        filters: list[str] = []
        for k, v in (params or {}).items():
            if k in _PAGINATION_KEYS:
                q[k] = str(v)
            else:
                filters.append(f"{k}:{v}")
        if filters:
            q["q"] = " ".join(filters)
        return await self._do("GET", self._base_url + path, q)

    async def post(self, path: str) -> bytes:
        """POST <path> with no request body."""
        return await self._do("POST", self._base_url + path, {})

    async def _do(self, method: str, url: str, params: dict[str, str]) -> bytes:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        session = self._session or aiohttp.ClientSession()
        owned = self._session is None

        if self.verbose:
            print(f"> {method} {url} {params}", file=sys.stderr)

        try:
            async with session.request(
                method, url, params=params, headers=headers, timeout=_TIMEOUT
            ) as resp:
                body = await resp.read()
                if self.verbose:
                    print(f"< {resp.status} {body.decode(errors='replace').strip()}", file=sys.stderr)
                if resp.status != 200:
                    raise SolarAssistantError(resp.status, body.decode(errors="replace"))
                return body
        finally:
            if owned:
                await session.close()


@dataclass
class SiteOwner:
    id: int = 0
    email: str = ""
    first_name: str = ""
    last_name: str = ""


@dataclass
class Site:
    id: int = 0
    name: str = ""
    inverter: str = ""
    inverter_count: int = 0
    inverter_params: dict[str, Any] = field(default_factory=dict)
    battery: str = ""
    battery_count: int = 0
    battery_params: dict[str, Any] = field(default_factory=dict)
    proxy: str = ""
    arch: str = ""
    board: str = ""
    beta: bool = False
    build_date: str = ""
    last_seen_at: str = ""
    local_ip: str = ""
    owner: SiteOwner = field(default_factory=SiteOwner)


@dataclass
class AuthorizeResponse:
    host: str = ""
    site_id: int = 0
    site_name: str = ""
    site_key: str = ""
    token: str = ""
    local_ip: str = ""


async def list_sites(client: SolarAssistantClient, **params: Any) -> list[Site]:
    """Return all sites accessible with the client's API key.

    Keyword arguments are passed as filters (e.g. ``inverter="srne"``,
    ``limit=50``).
    """
    body = await client.get(_SITES_PATH, params or None)
    return [_parse_site(s) for s in json.loads(body)]


async def authorize_site(client: SolarAssistantClient, site_id: int) -> AuthorizeResponse:
    """Return a short-lived token for connecting to a site's WebSocket."""
    body = await client.post(_AUTHORIZE_PATH.format(site_id=site_id))
    r = json.loads(body)
    return AuthorizeResponse(
        host=r.get("host", ""),
        site_id=r.get("site_id", 0),
        site_name=r.get("site_name", ""),
        site_key=r.get("site_key", ""),
        token=r.get("token", ""),
        local_ip=r.get("local_ip", ""),
    )


def _parse_site(s: dict[str, Any]) -> Site:
    o = s.get("owner") or {}
    return Site(
        id=s.get("id", 0),
        name=s.get("name", ""),
        inverter=s.get("inverter", ""),
        inverter_count=s.get("inverter_count", 0),
        inverter_params=s.get("inverter_params") or {},
        battery=s.get("battery", ""),
        battery_count=s.get("battery_count", 0),
        battery_params=s.get("battery_params") or {},
        proxy=s.get("proxy", ""),
        arch=s.get("arch", ""),
        board=s.get("board", ""),
        beta=s.get("beta", False),
        build_date=s.get("build_date", ""),
        last_seen_at=s.get("last_seen_at", ""),
        local_ip=s.get("local_ip", ""),
        owner=SiteOwner(
            id=o.get("id", 0),
            email=o.get("email", ""),
            first_name=o.get("first_name", ""),
            last_name=o.get("last_name", ""),
        ),
    )
