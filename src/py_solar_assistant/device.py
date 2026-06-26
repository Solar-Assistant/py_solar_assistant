"""REST client for direct communication with SolarAssistant units."""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp

from ._errors import SolarAssistantError, http_error
from ._url import safe_url

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
                if resp.status != 200:
                    raise http_error("POST", url, resp.status)
        finally:
            if owned:
                await session.close()

    async def get_system_metrics(self) -> list[DeviceMetric]:
        """Fetch system metrics via ``GET /api/v1/system``.

        Returns the unit's system metric rows in the same shape as
        :meth:`get_metrics`. A non-200 raises :class:`SolarAssistantError`.
        """
        url = f"{self._scheme}://{self._host}/api/v1/system"
        return await self._get_rows(url)

    async def get_site_id(self) -> int | None:
        """Return the unit's numeric ``site_id`` from ``GET /api/v1/system``.

        ``None`` when the ``site_id`` row is absent, the unit is unregistered (the
        value is null), or it can't be read as an int. A non-200 raises.
        """
        return _as_int(await self._system_value("system/site_id"))

    async def get_software_version(self) -> str | None:
        """Return the unit's software/build version from ``GET /api/v1/system``.

        ``None`` when the value is unset (null or blank). A non-200 raises.
        """
        return _as_str(await self._system_value("system/software_version"))

    async def get_cpu_temperature(self) -> int | None:
        """Return the unit's CPU temperature in °C from ``GET /api/v1/system``.

        ``None`` when the sensor read failed or the value can't be read as an int.
        A non-200 raises.
        """
        return _as_int(await self._system_value("system/cpu_temperature"))

    async def get_free_storage(self) -> int | None:
        """Return free root-filesystem storage in MB from ``GET /api/v1/system``.

        ``None`` when the read failed or the value can't be read as an int. A
        non-200 raises.
        """
        return _as_int(await self._system_value("system/free_storage"))

    async def _system_value(self, topic: str) -> Any:
        """Raw value of one ``/api/v1/system`` row, or ``None`` if that row is absent.

        Each accessor fetches the endpoint independently; to read several values
        in one request use :meth:`get_system_metrics` and pick them out yourself.
        """
        for m in await self.get_system_metrics():
            if m.topic == topic:
                return m.value
        return None

    async def _fetch(self, topic: str | None, *, discovery: bool) -> list[DeviceMetric]:
        params: list[str] = []
        if discovery:
            params.append("discovery")
        if topic:
            params.append(f"topic={quote(topic, safe='')}")
        query = ("?" + "&".join(params)) if params else ""
        url = f"{self._scheme}://{self._host}/api/v1/metrics{query}"
        return await self._get_rows(url)

    async def _get_rows(self, url: str) -> list[DeviceMetric]:
        """GET ``url`` and parse its JSON array into ``DeviceMetric`` rows.

        Any non-200 raises; a 200 whose body isn't a JSON array
        of objects raises rather than crashing ``_row_to_metric``.
        """
        auth, headers = _device_auth(self._password, self._token, self._site_id, self._site_key)
        session, owned = self._session_or_new()
        try:
            async with session.get(
                url,
                auth=auth,
                headers=headers,
                timeout=self._timeout,
            ) as resp:
                if resp.status != 200:
                    raise http_error("GET", url, resp.status)

                body = await resp.read()
                try:
                    rows = _json.loads(body)
                except ValueError as err:
                    raise SolarAssistantError(None, f"invalid JSON from {safe_url(url)}") from err
        finally:
            if owned:
                await session.close()

        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise SolarAssistantError(
                None, f"expected a JSON array of objects from {safe_url(url)}"
            )

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


async def get_device_system_metrics(
    host: str,
    *,
    password: str | None = None,
    token: str | None = None,
    scheme: str = "http",
    timeout: float = 10.0,
    site_id: int = 0,
    site_key: str = "",
) -> list[DeviceMetric]:
    """Fetch ``GET /api/v1/system`` from a SolarAssistant unit.

    Returns the system metric rows; a non-200 raises :class:`SolarAssistantError`.
    See :meth:`DeviceClient.get_system_metrics`.

    Auth mirrors :func:`get_device_metrics`: ``password`` for local HTTP Basic,
    or ``token`` (plus ``site_id``/``site_key`` for a cloud-proxy host).
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
        return await c.get_system_metrics()


async def get_device_site_id(
    host: str,
    *,
    password: str | None = None,
    token: str | None = None,
    scheme: str = "http",
    timeout: float = 10.0,
) -> int | None:
    """Read the unit's numeric ``site_id`` via ``GET /api/v1/system``.

    Returns ``None`` when the unit is unregistered or the value is unreadable; a
    non-200 raises.

    Takes no cloud-proxy ``site_id`` / ``site_key`` params, unlike the other
    device helpers: ``site_id`` is one of them, so a caller that could supply
    them already knows it and has no reason to read it back. This helper is for
    discovering the ``site_id`` over a local (password) connection, where it
    isn't known up front.
    """
    async with DeviceClient(
        host,
        password=password,
        token=token,
        scheme=scheme,
        timeout=timeout,
    ) as c:
        return await c.get_site_id()


async def get_device_software_version(
    host: str,
    *,
    password: str | None = None,
    token: str | None = None,
    scheme: str = "http",
    timeout: float = 10.0,
    site_id: int = 0,
    site_key: str = "",
) -> str | None:
    """Read the unit's software/build version via ``GET /api/v1/system``.

    ``None`` if the value is unset; a non-200 raises. See
    :meth:`DeviceClient.get_software_version`.
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
        return await c.get_software_version()


async def get_device_cpu_temperature(
    host: str,
    *,
    password: str | None = None,
    token: str | None = None,
    scheme: str = "http",
    timeout: float = 10.0,
    site_id: int = 0,
    site_key: str = "",
) -> int | None:
    """Read the unit's CPU temperature in °C via ``GET /api/v1/system``.

    ``None`` if the read failed or the value is unreadable; a non-200 raises.
    See :meth:`DeviceClient.get_cpu_temperature`.
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
        return await c.get_cpu_temperature()


async def get_device_free_storage(
    host: str,
    *,
    password: str | None = None,
    token: str | None = None,
    scheme: str = "http",
    timeout: float = 10.0,
    site_id: int = 0,
    site_key: str = "",
) -> int | None:
    """Read free root-filesystem storage in MB via ``GET /api/v1/system``.

    ``None`` if the read failed or the value is unreadable; a non-200 raises.
    See :meth:`DeviceClient.get_free_storage`.
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
        return await c.get_free_storage()


def _as_int(value: Any) -> int | None:
    """Return an integer value, or ``None`` if it isn't one."""
    return value if isinstance(value, int) else None


def _as_str(value: Any) -> str | None:
    """Return a string value, or ``None`` if it isn't one or is blank."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


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
