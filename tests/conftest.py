"""Shared fixtures: real local aiohttp servers the clients run against.

The clients under test build their own ``aiohttp.ClientSession`` and dial a host
string we hand them, so aiohttp's ``TestClient`` / ``aiohttp_client`` fixtures
don't fit (they exist to *be* the client). Instead, each fixture below starts a
real ``aiohttp.test_utils.TestServer`` on an ephemeral 127.0.0.1 port, records
the requests it receives, and exposes ``host`` / ``url`` to inject into the
client. Per-server response behaviour is controlled through the ``cfg`` namespace.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer


@dataclass
class CapturedRequest:
    """A request the fake server received, for asserting what the client sent."""

    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


# Typed application keys (aiohttp warns on bare-string ``app[...]`` keys).
REQUESTS: web.AppKey[list[CapturedRequest]] = web.AppKey("requests", list)
CFG: web.AppKey[SimpleNamespace] = web.AppKey("cfg", SimpleNamespace)


async def _capture(request: web.Request) -> None:
    """Record a request onto its app's ``requests`` list."""
    body = await request.read() if request.body_exists else b""
    request.app[REQUESTS].append(
        CapturedRequest(
            method=request.method,
            path=request.path,
            query=dict(request.query),
            headers=dict(request.headers),
            body=body,
        )
    )


class RecordingServer:
    """A started ``TestServer`` plus the requests it has recorded."""

    def __init__(self, server: TestServer) -> None:
        self._server = server
        self.requests: list[CapturedRequest] = server.app[REQUESTS]
        self.cfg: SimpleNamespace = server.app[CFG]

    @property
    def host(self) -> str:
        """``host:port`` to pass as a ``DeviceClient`` host or ``Options.local_ip``."""
        return f"{self._server.host}:{self._server.port}"

    @property
    def url(self) -> str:
        """Base URL for ``SolarAssistantClient(base_url=...)``."""
        return f"http://{self.host}"

    @property
    def last_request(self) -> CapturedRequest:
        return self.requests[-1]


ServerFactory = Callable[..., Awaitable[RecordingServer]]


@pytest.fixture
async def make_server() -> AsyncIterator[ServerFactory]:
    """Factory that starts a recording server from a list of routes (auto-closed)."""
    started: list[TestServer] = []

    async def start(routes: list, *, cfg: SimpleNamespace | None = None) -> RecordingServer:
        app = web.Application()
        app[REQUESTS] = []
        app[CFG] = cfg if cfg is not None else SimpleNamespace()
        app.add_routes(routes)
        server = TestServer(app)
        await server.start_server()
        started.append(server)
        return RecordingServer(server)

    yield start
    for server in started:
        await server.close()


def _resp(body: Any, status: int) -> web.Response:
    """Build a response from a configured body (dict/list -> JSON, str/bytes -> raw)."""
    if body is None:
        return web.json_response({"error": "error"}, status=status)
    if isinstance(body, (dict, list)):
        return web.json_response(body, status=status)
    if isinstance(body, bytes):
        return web.Response(body=body, status=status)
    return web.Response(text=str(body), status=status)


@pytest.fixture
async def cloud_server(make_server: ServerFactory) -> RecordingServer:
    """Fake cloud API: ``GET /api/v1/sites`` and ``POST /api/v1/sites/{id}/authorize``."""
    cfg = SimpleNamespace(sites=[], authorize={}, status=200, error_body=None)

    async def list_sites(request: web.Request) -> web.Response:
        await _capture(request)
        if cfg.status != 200:
            return _resp(cfg.error_body, cfg.status)
        return web.json_response(cfg.sites)

    async def authorize(request: web.Request) -> web.Response:
        await _capture(request)
        if cfg.status != 200:
            return _resp(cfg.error_body, cfg.status)
        return web.json_response(cfg.authorize)

    return await make_server(
        [
            web.get("/api/v1/sites", list_sites),
            web.post("/api/v1/sites/{site_id}/authorize", authorize),
        ],
        cfg=cfg,
    )


@pytest.fixture
async def device_server(make_server: ServerFactory) -> RecordingServer:
    """Fake device REST: ``GET`` and ``POST`` ``/api/v1/metrics``.

    ``cfg.rows`` is returned for every GET, unless ``cfg.rows_by_topic`` (a
    ``{topic: rows}`` map keyed by the ``?topic=`` value, ``None`` for no filter)
    is set. Error responses come from ``cfg.get_status``/``cfg.get_body`` and
    ``cfg.post_status``/``cfg.post_body``.

    ``GET /api/v1/system`` returns ``cfg.system_rows`` (status
    ``cfg.system_status``/body ``cfg.system_body`` on error), or
    ``cfg.system_raw`` (bytes) to return a non-JSON 200 body verbatim.
    """
    cfg = SimpleNamespace(
        rows=[],
        rows_by_topic=None,
        get_status=200,
        get_body=None,
        post_status=200,
        post_body=None,
        system_rows=[],
        system_status=200,
        system_body=None,
        system_raw=None,
    )

    async def get_metrics(request: web.Request) -> web.Response:
        await _capture(request)
        if cfg.get_status != 200:
            return _resp(cfg.get_body, cfg.get_status)
        if cfg.rows_by_topic is not None:
            rows = cfg.rows_by_topic.get(request.query.get("topic"), [])
        else:
            rows = cfg.rows
        return web.json_response(rows)

    async def get_system(request: web.Request) -> web.Response:
        await _capture(request)
        if cfg.system_status != 200:
            return _resp(cfg.system_body, cfg.system_status)
        if cfg.system_raw is not None:
            return web.Response(body=cfg.system_raw, content_type="text/html")
        return web.json_response(cfg.system_rows)

    async def set_metric(request: web.Request) -> web.Response:
        await _capture(request)
        if cfg.post_status != 200:
            return _resp(cfg.post_body, cfg.post_status)
        return web.json_response({})

    return await make_server(
        [
            web.get("/api/v1/metrics", get_metrics),
            web.get("/api/v1/system", get_system),
            web.post("/api/v1/metrics", set_metric),
        ],
        cfg=cfg,
    )


@pytest.fixture
async def ws_server(make_server: ServerFactory) -> RecordingServer:
    """Fake Phoenix Channels WebSocket at ``GET /api/websocket``.

    Frames are JSON arrays ``[join_ref, ref, topic, event, payload]``. On
    ``phx_join`` it replies ``phx_reply`` (status ``cfg.join_status``), then
    optionally pushes a ``definition`` event (``cfg.definitions``), a ``data``
    event (``cfg.data``), and any verbatim ``cfg.push_frames``; it closes the
    socket afterwards when ``cfg.close_after_join`` is set. On ``set`` it replies
    ``set_result`` (``cfg.set_result`` / ``cfg.set_message``). Every received
    frame is appended to ``cfg.received_frames``. Set ``cfg.upgrade_status`` to
    reject the handshake with that HTTP status instead of upgrading.
    """
    cfg = SimpleNamespace(
        join_status="ok",
        join_response={},
        definitions=None,
        data=None,
        push_frames=None,
        set_result="ok",
        set_message=None,
        upgrade_status=None,
        close_after_join=False,
        received_frames=[],
    )

    async def websocket(request: web.Request) -> web.StreamResponse:
        await _capture(request)
        if cfg.upgrade_status is not None:
            return web.Response(status=cfg.upgrade_status)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type is not aiohttp.WSMsgType.TEXT:
                continue
            frame = json.loads(msg.data)
            cfg.received_frames.append(frame)
            join_ref, ref, topic, event, payload = frame
            if event == "phx_join":
                await ws.send_str(
                    json.dumps(
                        [
                            join_ref,
                            ref,
                            topic,
                            "phx_reply",
                            {"status": cfg.join_status, "response": cfg.join_response},
                        ]
                    )
                )
                if cfg.definitions is not None:
                    await ws.send_str(
                        json.dumps(
                            [join_ref, None, topic, "definition", {"definitions": cfg.definitions}]
                        )
                    )
                if cfg.data is not None:
                    await ws.send_str(
                        json.dumps([join_ref, None, topic, "data", {"metrics": cfg.data}])
                    )
                for raw in cfg.push_frames or []:
                    await ws.send_str(json.dumps(raw))
                if cfg.close_after_join:
                    await ws.close()
            elif event == "set":
                reply = {"topic": payload.get("topic"), "result": cfg.set_result}
                if cfg.set_message is not None:
                    reply["message"] = cfg.set_message
                await ws.send_str(json.dumps([join_ref, None, topic, "set_result", reply]))
            elif event == "heartbeat":
                await ws.send_str(
                    json.dumps(
                        [None, ref, "phoenix", "phx_reply", {"status": "ok", "response": {}}]
                    )
                )
        return ws

    return await make_server([web.get("/api/websocket", websocket)], cfg=cfg)
