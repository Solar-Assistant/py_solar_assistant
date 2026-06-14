"""Tests for the WebSocket client (``socket.py``).

Everything runs the real client against the ``ws_server`` Phoenix fixture over a
real ``ws://`` connection. The one internal tested directly is ``_dial``: its
cloud ``site-id``/``site-key`` header logic only runs on the ``wss://`` path,
which needs a TLS server we can't stand up locally.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp
import pytest
from aiohttp.test_utils import unused_port

from py_solar_assistant import (
    ChannelError,
    ConnectError,
    Message,
    Metric,
    Options,
    TopicFilter,
    connect,
)
from py_solar_assistant.socket import _dial

# ---------------------------------------------------------------------------
# connect()


class TestConnect:
    async def test_requires_host_or_local_ip(self):
        with pytest.raises(ConnectError, match="No reachable host"):
            await connect(Options())

    async def test_local_password_connection(self, ws_server):
        sock = await connect(Options(local_ip=ws_server.host, password="secret"))
        assert sock.connected_host == ws_server.host
        await sock.close()
        request = ws_server.last_request
        assert request.query["vsn"] == "2.0.0"
        assert request.query["password"] == "secret"

    async def test_local_token_connection_sends_no_site_headers(self, ws_server):
        sock = await connect(Options(local_ip=ws_server.host, token="jwt"))
        assert sock.connected_host == ws_server.host
        await sock.close()
        request = ws_server.last_request
        assert request.query["token"] == "jwt"
        assert request.query["vsn"] == "2.0.0"
        assert "site-id" not in request.headers  # local branch never sends them

    async def test_unreachable_local_without_host_raises(self):
        dead = f"127.0.0.1:{unused_port()}"
        with pytest.raises(ConnectError):
            await connect(Options(local_ip=dead, password="x"))

    async def test_local_failure_falls_through_to_cloud(self, ws_server):
        # Dead local_ip with a host set: connect() should fall through to the cloud
        # branch rather than abort at the local address, so the error must not
        # mention the local address.
        dead = f"127.0.0.1:{unused_port()}"
        with pytest.raises(ConnectError) as excinfo:
            await connect(
                Options(local_ip=dead, host=ws_server.host, token="jwt", site_id=1, site_key="k")
            )
        assert dead not in str(excinfo.value)

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, "authentication failed"),
            (403, "authentication failed"),
            (404, "outdated"),
            (502, "offline or unreachable"),
            (500, "connection rejected"),
        ],
    )
    async def test_handshake_error_is_mapped_to_a_message(self, ws_server, status, expected):
        ws_server.cfg.upgrade_status = status
        with pytest.raises(ConnectError) as excinfo:
            await connect(Options(local_ip=ws_server.host, password="x"))
        assert expected in str(excinfo.value)


class TestDial:
    async def test_cloud_dial_sends_token_query_and_site_headers(self, ws_server):
        session = aiohttp.ClientSession()
        try:
            ws = await _dial(session, "ws", ws_server.host, "jwt", False, 42, "skey", 5.0, False)
            await ws.close()
        finally:
            await session.close()
        request = ws_server.last_request
        assert request.query["token"] == "jwt"
        assert request.query["vsn"] == "2.0.0"
        assert request.headers["site-id"] == "42"
        assert request.headers["site-key"] == "skey"


# ---------------------------------------------------------------------------
# subscribe_metrics / listen


class TestSubscribeMetrics:
    async def test_merges_definition_into_data(self, ws_server):
        ws_server.cfg.definitions = [
            {
                "topic": "total/pv_power",
                "device": "total",
                "number": None,
                "group": "Info",
                "name": "PV Power",
                "unit": "W",
                "platform": "sensor",
                "device_class": "power",
                "state_class": "measurement",
                "unit_of_measurement": "W",
                "min": 0,
                "max": 10000,
            }
        ]
        ws_server.cfg.data = [{"topic": "total/pv_power", "value": 1234}]
        ws_server.cfg.close_after_join = True

        sock = await connect(Options(local_ip=ws_server.host, password="secret"))
        received: list[Metric] = []
        await sock.subscribe_metrics(received.append)
        await asyncio.wait_for(sock.listen(), timeout=2)
        await sock.close()

        assert len(received) == 1
        metric = received[0]
        assert isinstance(metric, Metric)
        assert metric.topic == "total/pv_power"
        assert metric.value == 1234  # from the data event
        assert metric.name == "PV Power"  # from the definition event
        assert metric.unit == "W"
        assert metric.device == "total"
        assert metric.platform == "sensor"  # discovery metadata merged in
        assert metric.device_class == "power"
        assert metric.min == 0
        assert metric.max == 10000

    async def test_metric_without_a_definition_has_empty_metadata(self, ws_server):
        ws_server.cfg.data = [{"topic": "unknown/x", "value": 5}]
        ws_server.cfg.close_after_join = True

        sock = await connect(Options(local_ip=ws_server.host, password="x"))
        received: list[Metric] = []
        await sock.subscribe_metrics(received.append)
        await asyncio.wait_for(sock.listen(), timeout=2)
        await sock.close()

        assert len(received) == 1
        metric = received[0]
        assert metric.topic == "unknown/x"
        assert metric.value == 5
        assert metric.name == ""
        assert metric.device == ""
        assert metric.unit == ""
        assert metric.platform is None

    async def test_topic_filters_are_sent_in_the_join_payload(self, ws_server):
        ws_server.cfg.close_after_join = True
        sock = await connect(Options(local_ip=ws_server.host, password="x"))
        await sock.subscribe_metrics(
            lambda m: None,
            TopicFilter("total/*"),
            TopicFilter("battery_*/voltage", max_frequency_s=10),
        )
        await asyncio.wait_for(sock.listen(), timeout=2)
        await sock.close()

        join = next(f for f in ws_server.cfg.received_frames if f[3] == "phx_join")
        assert join[4] == {
            "topics": [
                {"topic": "total/*"},
                {"topic": "battery_*/voltage", "max_frequency_s": 10},
            ]
        }

    async def test_no_filters_sends_an_empty_join_payload(self, ws_server):
        ws_server.cfg.close_after_join = True
        sock = await connect(Options(local_ip=ws_server.host, password="x"))
        await sock.subscribe_metrics(lambda m: None)
        await asyncio.wait_for(sock.listen(), timeout=2)
        await sock.close()

        join = next(f for f in ws_server.cfg.received_frames if f[3] == "phx_join")
        assert join[4] == {}


class TestDispatch:
    async def test_wildcard_subscription_receives_pushed_frames(self, ws_server):
        ws_server.cfg.push_frames = [["1", None, "weather", "update", {"temp": 21}]]
        ws_server.cfg.close_after_join = True

        sock = await connect(Options(local_ip=ws_server.host, password="x"))
        seen: list[Message] = []
        sock.subscribe("*", "*", seen.append)
        await sock.join("metrics")
        await asyncio.wait_for(sock.listen(), timeout=2)
        await sock.close()

        assert ("weather", "update") in [(m.topic, m.event) for m in seen]

    async def test_malformed_frames_are_dropped_without_crashing(self, ws_server):
        ws_server.cfg.push_frames = [
            ["1", "2", "short"],  # fewer than 5 elements -> dropped
            {"not": "an array"},  # not a frame array -> dropped
            ["1", None, "weather", "update", {"temp": 21}],  # valid -> dispatched
        ]
        ws_server.cfg.close_after_join = True

        sock = await connect(Options(local_ip=ws_server.host, password="x"))
        seen: list[Message] = []
        sock.subscribe("*", "*", seen.append)
        await sock.join("metrics")
        await asyncio.wait_for(sock.listen(), timeout=2)
        await sock.close()

        events = [(m.topic, m.event) for m in seen]
        assert ("weather", "update") in events
        # only the join reply and the one valid frame got through; the rest dropped
        assert len(seen) == 2

    async def test_listen_raises_channel_error_on_phx_error(self, ws_server):
        ws_server.cfg.push_frames = [["1", None, "metrics", "phx_error", {}]]
        sock = await connect(Options(local_ip=ws_server.host, password="x"))
        await sock.join("metrics")
        with pytest.raises(ChannelError):
            await asyncio.wait_for(sock.listen(), timeout=2)
        await sock.close()

    async def test_listen_raises_channel_error_on_join_failure(self, ws_server):
        ws_server.cfg.join_status = "error"
        ws_server.cfg.join_response = {"reason": "unauthorized"}
        sock = await connect(Options(local_ip=ws_server.host, password="x"))
        await sock.subscribe_metrics(lambda m: None)
        with pytest.raises(ChannelError):
            await asyncio.wait_for(sock.listen(), timeout=2)
        await sock.close()


# ---------------------------------------------------------------------------
# set_setting


class TestSetSetting:
    async def test_success_sends_join_then_set(self, ws_server):
        sock = await connect(Options(local_ip=ws_server.host, password="x"))
        await asyncio.wait_for(sock.set_setting("inverter_1/power_mode", "Off grid"), timeout=2)
        await sock.close()

        received = ws_server.cfg.received_frames
        assert [f[3] for f in received] == ["phx_join", "set"]  # join precedes the set
        assert received[1][4] == {"topic": "inverter_1/power_mode", "value": "Off grid"}

    async def test_error_result_raises_value_error(self, ws_server):
        ws_server.cfg.set_result = "error"
        ws_server.cfg.set_message = "value rejected"
        sock = await connect(Options(local_ip=ws_server.host, password="x"))
        with pytest.raises(ValueError, match="value rejected"):
            await asyncio.wait_for(sock.set_setting("inverter_1/x", "bad"), timeout=2)
        await sock.close()


# ---------------------------------------------------------------------------
# verbose logging


class TestVerboseLogging:
    async def test_token_is_redacted_in_debug_log(self, ws_server, caplog):
        with caplog.at_level(logging.DEBUG, logger="py_solar_assistant.socket"):
            sock = await connect(
                Options(local_ip=ws_server.host, token="supersecret", verbose=True)
            )
            await sock.close()
        assert "[REDACTED]" in caplog.text
        assert "supersecret" not in caplog.text
