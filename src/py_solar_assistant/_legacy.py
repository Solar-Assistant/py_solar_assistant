"""The older way of doing things, for SolarAssistant builds that predate the current API.

Remove each function once the builds that need it are no longer supported.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .device import DeviceClient, DeviceMetric
    from .socket import Message, MetricHandler, Socket, TopicFilter


async def system_metrics(client: DeviceClient) -> list[DeviceMetric]:
    """Builds before 2026-10-12 list no ``system/*`` rows on ``/api/v1/metrics``.

    Units keep ``/api/v1/system`` until at least October 2027, so a unit
    upgraded under a running client is still read correctly.
    """
    return await client._get_rows(client._url("/api/v1/system"))


def subscribe_system_event(
    sock: Socket, handler: MetricHandler, filters: tuple[TopicFilter, ...]
) -> None:
    """Builds before 2026-10-12 send ``system/*`` only as a separate ``system`` event.

    Newer builds send the event too, just ahead of the same values in the stream,
    so it is ignored once the stream has carried any ``system/*`` metric.
    """
    fallback = _SystemEventFallback(sock, handler, filters)
    sock.subscribe("metrics", "data", fallback.on_data)
    sock.subscribe("metrics", "system", fallback.on_system)


class _SystemEventFallback:
    def __init__(
        self, sock: Socket, handler: MetricHandler, filters: tuple[TopicFilter, ...]
    ) -> None:
        self._sock = sock
        self._handler = handler
        self._filters = filters
        self._streamed = False

    def on_data(self, msg: Message) -> None:
        if self._streamed:
            return
        self._streamed = any(
            item.get("topic", "").startswith("system/") for item in msg.payload.get("metrics", [])
        )

    def on_system(self, msg: Message) -> None:
        if self._streamed:
            return
        for item in msg.payload.get("metrics", []):
            if any(fnmatchcase(item.get("topic", ""), f.topic) for f in self._filters):
                self._handler(self._sock._metric(item))
