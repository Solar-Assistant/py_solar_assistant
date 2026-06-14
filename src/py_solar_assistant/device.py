"""REST client for direct communication with SolarAssistant units."""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp

from .cloud import SolarAssistantError

_DEVICE_REST_USERNAME = "admin"


@dataclass
class DeviceMetric:
    """One row from ``GET /api/v1/metrics`` on a SolarAssistant unit.

    Discovery fields (``platform``, ``device_class``, ``state_class``,
    ``unit_of_measurement``, ``min``, ``max``, ``options``,
    ``payload_on``, ``payload_off``) are populated only when the request
    used ``?discovery``; otherwise they're ``None``.
    """

    topic: str
    name: str
    unit: str
    value: Any
    group: str
    device: str
    number: int | None
    platform: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    unit_of_measurement: str | None = None
    min: float | None = None
    max: float | None = None
    options: list[str] | None = None
    payload_on: str | None = None
    payload_off: str | None = None


class DeviceClient:
    """REST client for a SolarAssistant device with connection reuse.

    Prefer this over the standalone :func:`get_device_metrics` /
    :func:`set_metric` when making multiple calls to the same device.

    Usage::

        async with DeviceClient("192.168.1.100", password="secret") as c:
            metrics = await c.get_metrics()
            await c.set_metric("inverter_1/charge_current_limit", "40")

        # Multi-topic with deduplication
        async with DeviceClient("192.168.1.100", password="secret") as c:
            metrics = await c.get_metrics("total/*", "battery_1/*")
    """

    def __init__(
        self,
        host: str,
        *,
        password: str | None = None,
        token: str | None = None,
        site_id: int = 0,
        site_key: str = "",
        scheme: str = "http",
        timeout: float = 10.0,
    ) -> None:
        if not password and not token:
            raise ValueError("DeviceClient requires password or token")
        self._host = host
        self._password = password
        self._token = token
        self._site_id = site_id
        self._site_key = site_key
        self._scheme = scheme
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> DeviceClient:
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def get_metrics(self, *topics: str, discovery: bool = True) -> list[DeviceMetric]:
        """Fetch metrics via ``GET /api/v1/metrics``.

        Pass topic glob patterns to filter (e.g. ``"battery_1/*"``,
        ``"total/pv_power"``). Multiple topics are fetched in separate
        requests and deduplicated. Omit to fetch all metrics.
        """
        if not topics:
            return await self._fetch(None, discovery=discovery)
        seen: set[str] = set()
        result: list[DeviceMetric] = []
        for topic in topics:
            for m in await self._fetch(topic, discovery=discovery):
                if m.topic not in seen:
                    seen.add(m.topic)
                    result.append(m)
        return result

    async def set_metric(self, topic: str, value: str) -> None:
        """Write a setting via ``POST /api/v1/metrics``.

        Args:
            topic: MQTT-style topic, e.g. ``"inverter_1/charge_current_limit"``.
            value: New value as a string.
        """
        url = f"{self._scheme}://{self._host}/api/v1/metrics"
        auth, headers = _device_auth(self._password, self._token, self._site_id, self._site_key)
        session, owned = self._session_or_new()
        try:
            async with session.post(
                url,
                json={"topic": topic, "value": value},
                auth=auth,
                headers=headers,
                timeout=self._timeout,
            ) as resp:
                body = await resp.read()
                if resp.status != 200:
                    try:
                        msg = _json.loads(body).get("error", body.decode(errors="replace"))
                    except Exception:
                        msg = body.decode(errors="replace")
                    raise SolarAssistantError(resp.status, msg)
        finally:
            if owned:
                await session.close()

    async def _fetch(self, topic: str | None, *, discovery: bool) -> list[DeviceMetric]:
        params: list[str] = []
        if discovery:
            params.append("discovery")
        if topic:
            params.append(f"topic={quote(topic, safe='')}")
        query = ("?" + "&".join(params)) if params else ""
        url = f"{self._scheme}://{self._host}/api/v1/metrics{query}"
        auth, headers = _device_auth(self._password, self._token, self._site_id, self._site_key)
        session, owned = self._session_or_new()
        try:
            async with session.get(
                url,
                auth=auth,
                headers=headers,
                timeout=self._timeout,
            ) as resp:
                body = await resp.read()
                if resp.status != 200:
                    raise SolarAssistantError(resp.status, body.decode(errors="replace"))
                rows = _json.loads(body)
        finally:
            if owned:
                await session.close()
        return [_row_to_metric(r) for r in rows]

    def _session_or_new(self) -> tuple[aiohttp.ClientSession, bool]:
        if self._session:
            return self._session, False
        return aiohttp.ClientSession(), True


def _device_auth(
    password: str | None,
    token: str | None,
    site_id: int,
    site_key: str,
) -> tuple[aiohttp.BasicAuth | None, dict[str, str]]:
    if password:
        return aiohttp.BasicAuth(_DEVICE_REST_USERNAME, password), {}
    headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
    if site_id:
        headers["site-id"] = str(site_id)
    if site_key:
        headers["site-key"] = site_key
    return None, headers


async def get_device_metrics(
    host: str,
    *,
    password: str | None = None,
    token: str | None = None,
    discovery: bool = True,
    topic: str | None = None,
    scheme: str = "http",
    timeout: float = 10.0,
    site_id: int = 0,
    site_key: str = "",
) -> list[DeviceMetric]:
    """Fetch ``GET /api/v1/metrics`` from a SolarAssistant unit.

    Auth: pass ``password`` for local HTTP Basic (``admin:<web-password>``),
    or ``token`` for a Bearer-style JWT. For a cloud-proxy host also pass
    ``site_id`` and ``site_key`` so the proxy can route to the unit.

    Set ``discovery=True`` (default) to request the HA-discovery superset
    (``platform``, ``device_class``, ``min``/``max``/``options``/etc.).
    Set ``topic="inverter_1/foo"`` to filter the response to a single metric.
    """
    async with DeviceClient(
        host,
        password=password,
        token=token,
        site_id=site_id,
        site_key=site_key,
        scheme=scheme,
        timeout=timeout,
    ) as c:
        return await c.get_metrics(*([topic] if topic else []), discovery=discovery)


async def set_metric(
    host: str,
    topic: str,
    value: str,
    *,
    password: str | None = None,
    token: str | None = None,
    scheme: str = "http",
    timeout: float = 10.0,
    site_id: int = 0,
    site_key: str = "",
) -> None:
    """Write a setting via ``POST /api/v1/metrics``.

    Args:
        host: IP address or hostname of the SolarAssistant device.
        topic: MQTT-style topic, e.g. ``"inverter_1/power_mode"``.
        value: New value as a string.
        site_id: Required for cloud-proxy connections.
        site_key: Required for cloud-proxy connections.

    Raises:
        SolarAssistantError: If the server returns an error.
    """
    async with DeviceClient(
        host,
        password=password,
        token=token,
        site_id=site_id,
        site_key=site_key,
        scheme=scheme,
        timeout=timeout,
    ) as c:
        await c.set_metric(topic, value)


def _row_to_metric(r: dict[str, Any]) -> DeviceMetric:
    return DeviceMetric(
        topic=r.get("topic", "") or "",
        name=r.get("name", "") or "",
        unit=r.get("unit", "") or "",
        value=r.get("value"),
        group=r.get("group", "") or "",
        device=r.get("device", "") or "",
        number=r.get("number"),
        platform=r.get("platform"),
        device_class=r.get("device_class"),
        state_class=r.get("state_class"),
        unit_of_measurement=r.get("unit_of_measurement"),
        min=r.get("min"),
        max=r.get("max"),
        options=r.get("options"),
        payload_on=r.get("payload_on"),
        payload_off=r.get("payload_off"),
    )
