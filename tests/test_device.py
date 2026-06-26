"""Tests for the device REST client (``device.py``)."""

from __future__ import annotations

import base64

import pytest

from py_solar_assistant import (
    DeviceClient,
    DeviceMetric,
    SolarAssistantError,
    get_device_cpu_temperature,
    get_device_free_storage,
    get_device_metrics,
    get_device_site_id,
    get_device_software_version,
    get_device_system_metrics,
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


def system_row(topic: str = "system/site_id", **over: object) -> dict:
    """A ``/api/v1/system`` row as the device returns it (no ``number``/``unit``)."""
    base = {
        "topic": topic,
        "device": "system",
        "group": "Info",
        "name": "Site ID",
        "value": 12345,
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

    async def test_error_carries_status_not_body(self, device_server):
        # Non-200 raises with the status; the body is never echoed -- not even a
        # credential in free text, which key-based redaction couldn't scrub. The
        # body isn't read on the error path, so its type (JSON or not) is moot.
        device_server.cfg.post_status = 400
        device_server.cfg.post_body = {"error": "denied for token=topsecret"}
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError) as excinfo:
                await c.set_metric("inverter_1/x", "9999")
        assert excinfo.value.status == 400
        assert "topsecret" not in str(excinfo.value)


class TestGetMetricsErrors:
    async def test_non_200_raises_with_status(self, device_server):
        device_server.cfg.get_status = 401
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError) as excinfo:
                await c.get_metrics()
        assert excinfo.value.status == 401

    async def test_error_does_not_surface_server_body(self, device_server):
        # The message is method + endpoint + status, never the body -- not even a
        # credential in free text, which key-based redaction couldn't scrub. That's
        # why the body is dropped wholesale rather than filtered.
        device_server.cfg.get_status = 500
        device_server.cfg.get_body = {"error": "auth failed for token=topsecret"}
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError) as excinfo:
                await c.get_metrics()
        msg = str(excinfo.value)
        assert excinfo.value.status == 500
        assert "GET" in msg and "/api/v1/metrics" in msg
        assert "topsecret" not in msg

    async def test_non_list_200_body_raises(self, device_server):
        # The /metrics path shares the transport, so it inherits the same
        # array-shape guard as /system rather than crashing _row_to_metric.
        device_server.cfg.rows = {"error": "not a list"}
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError, match="JSON array"):
                await c.get_metrics()


class TestSystemMetrics:
    async def test_hits_system_endpoint(self, device_server):
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            await c.get_system_metrics()
        assert device_server.last_request.path == "/api/v1/system"

    async def test_parses_system_rows(self, device_server):
        device_server.cfg.system_rows = [
            system_row(),
            system_row(
                "system/free_storage", group="Status", name="Free storage", value=8192, unit="MB"
            ),
        ]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            metrics = await c.get_system_metrics()
        assert [m.topic for m in metrics] == ["system/site_id", "system/free_storage"]
        assert metrics[0].value == 12345
        assert metrics[1].unit == "MB"

    async def test_non_200_raises(self, device_server):
        # 404 isn't special-cased -- it raises like any other non-200 (regression
        # guard for the removed old-firmware None-handling). The status propagates.
        device_server.cfg.system_status = 404
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError) as excinfo:
                await c.get_system_metrics()
        assert excinfo.value.status == 404

    async def test_error_does_not_surface_server_body(self, device_server):
        # Non-200 raises with the status; the body is never echoed -- not even a
        # credential in free text, which key-based redaction couldn't scrub. Any
        # shape of error body yields the same clean, body-free error.
        device_server.cfg.system_status = 500
        device_server.cfg.system_body = {"error": "denied for token=topsecret"}
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError) as excinfo:
                await c.get_system_metrics()
        msg = str(excinfo.value)
        assert excinfo.value.status == 500
        assert "GET" in msg and "/api/v1/system" in msg
        assert "topsecret" not in msg

    @pytest.mark.parametrize("body", [{"error": "boom"}, "oops", 42])
    async def test_non_list_200_body_raises(self, device_server, body):
        # A malformed 200 (object / error envelope / scalar) is an error, not a
        # crash and not a silent empty result.
        device_server.cfg.system_rows = body
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError, match="JSON array"):
                await c.get_system_metrics()

    async def test_list_of_non_objects_raises(self, device_server):
        # The list container is fine but its elements aren't dicts — must raise,
        # not crash _row_to_metric with r.get(...).
        device_server.cfg.system_rows = [1, 2, 3]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError, match="JSON array"):
                await c.get_system_metrics()

    async def test_malformed_body_uses_synthetic_status_not_200(self, device_server):
        # A malformed 200 must not raise with status=200 (a caller branching on
        # err.status would read that as success).
        device_server.cfg.system_rows = {"error": "boom"}
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError) as excinfo:
                await c.get_system_metrics()
        assert excinfo.value.status is None

    async def test_invalid_json_200_raises_solarassistant_error(self, device_server):
        # A 200 with a non-JSON body (captive portal, bad proxy) is catchable,
        # not a raw json.JSONDecodeError.
        device_server.cfg.system_raw = b"<html>captive portal</html>"
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError, match="invalid JSON"):
                await c.get_system_metrics()

    async def test_synthetic_status_message_omits_literal_none(self, device_server):
        # status=None is a synthetic "no HTTP status" marker; it must not render
        # as the user-facing string "API error None: ...".
        device_server.cfg.system_raw = b"<html>captive portal</html>"
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            with pytest.raises(SolarAssistantError) as excinfo:
                await c.get_system_metrics()
        assert "None" not in str(excinfo.value)

    async def test_get_system_metrics_distinguishes_null_from_absent(self, device_server):
        # The full-fidelity path lets a caller tell "row present but null"
        # (unregistered -> retry) apart from "row absent" (firmware lacks it) --
        # the distinction get_site_id() intentionally collapses to None.
        device_server.cfg.system_rows = [system_row(value=None)]  # site_id present, null
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            metrics = await c.get_system_metrics()
        by_topic = {m.topic: m.value for m in metrics}
        assert by_topic["system/site_id"] is None  # present, unregistered
        assert "system/cpu_temperature" not in by_topic  # genuinely absent row

    async def test_get_site_id_returns_int(self, device_server):
        device_server.cfg.system_rows = [system_row(value=987654)]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            assert await c.get_site_id() == 987654

    async def test_get_site_id_none_when_unregistered(self, device_server):
        device_server.cfg.system_rows = [system_row(value=None)]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            assert await c.get_site_id() is None

    async def test_get_site_id_none_when_row_absent(self, device_server):
        device_server.cfg.system_rows = [
            system_row("system/free_storage", group="Status", name="Free storage", value=8192)
        ]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            assert await c.get_site_id() is None

    async def test_get_software_version(self, device_server):
        device_server.cfg.system_rows = [
            system_row("system/software_version", name="Software version", value="2026-06-15")
        ]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            assert await c.get_software_version() == "2026-06-15"

    @pytest.mark.parametrize("value", [None, "", "   "])
    async def test_get_software_version_unset_is_none(self, device_server, value):
        # null, blank, and whitespace-only all mean "unset" per the docstring —
        # none of them should leak through as a bogus version string.
        device_server.cfg.system_rows = [
            system_row("system/software_version", name="Software version", value=value)
        ]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            assert await c.get_software_version() is None

    async def test_get_cpu_temperature(self, device_server):
        device_server.cfg.system_rows = [
            system_row("system/cpu_temperature", group="Status", name="CPU temperature", value=47)
        ]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            assert await c.get_cpu_temperature() == 47

    async def test_get_cpu_temperature_float_is_none(self, device_server):
        # These metrics are integers on the wire, so a float isn't coerced -- no
        # silent truncation to 47. If a field ever becomes a float we'll return a
        # float, not an int.
        device_server.cfg.system_rows = [
            system_row("system/cpu_temperature", group="Status", name="CPU temp", value=47.8)
        ]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            assert await c.get_cpu_temperature() is None

    async def test_get_free_storage(self, device_server):
        device_server.cfg.system_rows = [
            system_row("system/free_storage", group="Status", name="Free storage", value=8192)
        ]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            assert await c.get_free_storage() == 8192

    async def test_one_fetch_serves_all_via_get_system_metrics(self, device_server):
        # The efficient path for several values: one request, pick them out.
        device_server.cfg.system_rows = [
            system_row(value=12345),
            system_row("system/software_version", name="Software version", value="2026-06-15"),
            system_row("system/free_storage", group="Status", name="Free storage", value=8192),
        ]
        async with DeviceClient(device_server.host, password="x", scheme="http") as c:
            metrics = await c.get_system_metrics()
        assert {m.topic: m.value for m in metrics} == {
            "system/site_id": 12345,
            "system/software_version": "2026-06-15",
            "system/free_storage": 8192,
        }
        assert len([r for r in device_server.requests if r.method == "GET"]) == 1


class TestStandaloneHelpers:
    async def test_get_device_metrics(self, device_server):
        device_server.cfg.rows = [row(value=7)]
        metrics = await get_device_metrics(device_server.host, password="x", scheme="http")
        assert metrics[0].value == 7

    async def test_get_device_system_metrics(self, device_server):
        device_server.cfg.system_rows = [system_row(value=42)]
        metrics = await get_device_system_metrics(device_server.host, password="x", scheme="http")
        assert metrics[0].value == 42

    async def test_get_device_site_id(self, device_server):
        device_server.cfg.system_rows = [system_row(value=24680)]
        assert await get_device_site_id(device_server.host, password="x", scheme="http") == 24680

    def test_get_device_site_id_has_no_routing_site_id_param(self):
        # No cloud-proxy site_id/site_key params: a caller that has them already
        # knows the site_id, so reading it back makes no sense. Passing one is an
        # error, not a silent misroute.
        with pytest.raises(TypeError):
            get_device_site_id("host", password="x", site_id=123)

    async def test_get_device_software_version(self, device_server):
        device_server.cfg.system_rows = [
            system_row("system/software_version", name="Software version", value="2026-06-15")
        ]
        version = await get_device_software_version(device_server.host, password="x", scheme="http")
        assert version == "2026-06-15"

    async def test_get_device_cpu_temperature(self, device_server):
        device_server.cfg.system_rows = [
            system_row("system/cpu_temperature", group="Status", name="CPU temperature", value=51)
        ]
        assert (
            await get_device_cpu_temperature(device_server.host, password="x", scheme="http") == 51
        )

    async def test_get_device_free_storage(self, device_server):
        device_server.cfg.system_rows = [
            system_row("system/free_storage", group="Status", name="Free storage", value=4096)
        ]
        assert (
            await get_device_free_storage(device_server.host, password="x", scheme="http") == 4096
        )

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
