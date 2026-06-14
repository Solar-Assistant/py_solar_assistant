"""Tests for the device REST client (``device.py``)."""

from __future__ import annotations

import base64

import pytest

from py_solar_assistant import (
    DeviceClient,
    DeviceMetric,
    SolarAssistantError,
    get_device_metrics,
    set_metric,
)


def row(topic: str = "total/pv_power", **over: object) -> dict:
    """A metrics row as the device returns it, with sensible defaults."""
    base = {
        "topic": topic,
        "name": "PV Power",
        "unit": "W",
        "value": 1234,
        "group": "Info",
        "device": "total",
        "number": None,
    }
    base.update(over)
    return base


class TestAuth:
    async def test_local_password_uses_basic_auth(self, device_server):
        async with DeviceClient(device_server.host, password="web-pw", scheme="http") as c:
            await c.get_metrics()
        header = device_server.last_request.headers["Authorization"]
        assert header.startswith("Basic ")
        login, password = base64.b64decode(header[len("Basic ") :]).decode().split(":", 1)
        assert login == "admin"
        assert password == "web-pw"

    async def test_token_uses_bearer_and_site_headers(self, device_server):
        async with DeviceClient(
            device_server.host, token="jwt", site_id=42, site_key="skey", scheme="http"
        ) as c:
            await c.get_metrics()
        headers = device_server.last_request.headers
        assert headers["Authorization"] == "Bearer jwt"
        assert headers["site-id"] == "42"
        assert headers["site-key"] == "skey"

    async def test_token_without_site_omits_site_headers(self, device_server):
        async with DeviceClient(device_server.host, token="jwt", scheme="http") as c:
            await c.get_metrics()
        headers = device_server.last_request.headers
        assert headers["Authorization"] == "Bearer jwt"
        assert "site-id" not in headers
        assert "site-key" not in headers

    def test_requires_password_or_token(self):
        with pytest.raises(ValueError, match="password or token"):
            DeviceClient("host")


class TestGetMetrics:
    async def test_parses_rows_to_metrics(self, device_server):
        device_server.cfg.rows = [row(value=999)]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            metrics = await c.get_metrics()
        assert len(metrics) == 1
        metric = metrics[0]
        assert isinstance(metric, DeviceMetric)
        assert metric.topic == "total/pv_power"
        assert metric.name == "PV Power"
        assert metric.value == 999
        assert metric.unit == "W"
        assert metric.device == "total"

    async def test_discovery_fields_populated(self, device_server):
        device_server.cfg.rows = [row(platform="sensor", device_class="power", min=0, max=5000)]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            metrics = await c.get_metrics(discovery=True)
        metric = metrics[0]
        assert metric.platform == "sensor"
        assert metric.device_class == "power"
        assert metric.min == 0
        assert metric.max == 5000

    async def test_discovery_flag_sent_by_default(self, device_server):
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            await c.get_metrics()
        assert "discovery" in device_server.last_request.query

    async def test_discovery_can_be_disabled(self, device_server):
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            await c.get_metrics(discovery=False)
        assert "discovery" not in device_server.last_request.query

    async def test_topic_glob_is_url_encoded_on_the_wire(self, device_server):
        device_server.cfg.rows_by_topic = {"battery_1/*": [row("battery_1/voltage")]}
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            metrics = await c.get_metrics("battery_1/*")
        # The server decoded the topic back to "battery_1/*", proving the client
        # percent-encoded the glob (`/` and `*`) correctly on the wire.
        assert device_server.last_request.query["topic"] == "battery_1/*"
        assert metrics[0].topic == "battery_1/voltage"

    async def test_multiple_topics_fetched_separately_and_deduped(self, device_server):
        device_server.cfg.rows_by_topic = {
            "total/*": [row("total/pv_power"), row("total/load_power")],
            "battery_1/*": [row("total/pv_power"), row("battery_1/voltage")],  # overlap
        }
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            metrics = await c.get_metrics("total/*", "battery_1/*")
        assert [m.topic for m in metrics] == [
            "total/pv_power",
            "total/load_power",
            "battery_1/voltage",
        ]
        gets = [r for r in device_server.requests if r.method == "GET"]
        assert len(gets) == 2  # one request per topic glob

    async def test_no_topics_makes_single_request(self, device_server):
        device_server.cfg.rows = [row()]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            await c.get_metrics()
        assert len([r for r in device_server.requests if r.method == "GET"]) == 1

    async def test_sparse_row_gets_defaults(self, device_server):
        device_server.cfg.rows = [{"topic": "x/y"}]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            metrics = await c.get_metrics()
        metric = metrics[0]
        assert metric.topic == "x/y"
        assert metric.name == ""
        assert metric.unit == ""
        assert metric.value is None
        assert metric.number is None
        assert metric.platform is None


class TestSetMetric:
    async def test_posts_topic_and_value(self, device_server):
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            await c.set_metric("inverter_1/charge_current_limit", "40")
        request = device_server.last_request
        assert request.method == "POST"
        assert request.json() == {"topic": "inverter_1/charge_current_limit", "value": "40"}

    async def test_error_extracts_json_error_field(self, device_server):
        device_server.cfg.post_status = 400
        device_server.cfg.post_body = {"error": "value out of range"}
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError) as excinfo:
                await c.set_metric("inverter_1/x", "9999")
        assert excinfo.value.status == 400
        assert "value out of range" in str(excinfo.value)

    async def test_error_falls_back_to_raw_body(self, device_server):
        device_server.cfg.post_status = 500
        device_server.cfg.post_body = "internal error"  # not JSON
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError) as excinfo:
                await c.set_metric("inverter_1/x", "1")
        assert excinfo.value.status == 500
        assert "internal error" in str(excinfo.value)


class TestGetMetricsErrors:
    async def test_non_200_raises_with_status(self, device_server):
        device_server.cfg.get_status = 401
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError) as excinfo:
                await c.get_metrics()
        assert excinfo.value.status == 401


class TestStandaloneHelpers:
    async def test_get_device_metrics(self, device_server):
        device_server.cfg.rows = [row(value=7)]
        metrics = await get_device_metrics(device_server.host, password="x", scheme="http")
        assert metrics[0].value == 7

    async def test_get_device_metrics_with_topic(self, device_server):
        device_server.cfg.rows_by_topic = {"total/pv_power": [row("total/pv_power")]}
        metrics = await get_device_metrics(
            device_server.host, password="x", topic="total/pv_power", scheme="http"
        )
        assert metrics[0].topic == "total/pv_power"
        assert device_server.last_request.query["topic"] == "total/pv_power"

    async def test_set_metric_standalone(self, device_server):
        await set_metric(
            device_server.host, "inverter_1/power_mode", "On", password="x", scheme="http"
        )
        assert device_server.last_request.json() == {
            "topic": "inverter_1/power_mode",
            "value": "On",
        }

    async def test_set_metric_standalone_raises_on_error(self, device_server):
        device_server.cfg.post_status = 400
        device_server.cfg.post_body = {"error": "nope"}
        with pytest.raises(SolarAssistantError):
            await set_metric(device_server.host, "x/y", "1", password="x", scheme="http")


class TestSessionReuse:
    async def test_context_manager_reuses_one_session(self, device_server):
        device_server.cfg.rows = [row()]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            await c.get_metrics()
            await c.set_metric("a/b", "1")
        assert len(device_server.requests) == 2

    async def test_call_without_context_manager_does_not_leak(self, device_server):
        # Without ``async with``, each call creates and closes its own session.
        # filterwarnings=error fails the test if that session leaks.
        c = DeviceClient(device_server.host, password="x", scheme="http")
        await c.get_metrics()
        await c.close()
