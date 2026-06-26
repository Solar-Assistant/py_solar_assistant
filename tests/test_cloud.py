"""Tests for the cloud REST client (``cloud.py``)."""

from __future__ import annotations

import logging

import pytest

from py_solar_assistant import (
    AuthorizeResponse,
    Site,
    SolarAssistantClient,
    SolarAssistantError,
    authorize_site,
    list_sites,
)


class TestQueryBuilding:
    """The ``?q=`` builder: pagination is top-level, search leads, rest are key:value."""

    async def test_search_becomes_leading_bare_term(self, cloud_server):
        async with SolarAssistantClient("key", base_url=cloud_server.url) as client:
            await list_sites(client, search="my-site")
        assert cloud_server.last_request.query["q"] == "my-site"

    async def test_filter_becomes_key_value_term(self, cloud_server):
        async with SolarAssistantClient("key", base_url=cloud_server.url) as client:
            await list_sites(client, inverter="srne")
        assert cloud_server.last_request.query["q"] == "inverter:srne"

    async def test_pagination_is_top_level_not_in_q(self, cloud_server):
        async with SolarAssistantClient("key", base_url=cloud_server.url) as client:
            await list_sites(client, limit=50, offset=20)
        query = cloud_server.last_request.query
        assert query["limit"] == "50"
        assert query["offset"] == "20"
        assert "q" not in query

    async def test_search_leads_regardless_of_argument_order(self, cloud_server):
        async with SolarAssistantClient("key", base_url=cloud_server.url) as client:
            await list_sites(client, inverter="srne", battery="daly", search="x")
        assert cloud_server.last_request.query["q"] == "x inverter:srne battery:daly"

    async def test_search_and_pagination_coexist(self, cloud_server):
        async with SolarAssistantClient("key", base_url=cloud_server.url) as client:
            await list_sites(client, search="home", limit=10)
        query = cloud_server.last_request.query
        assert query["q"] == "home"
        assert query["limit"] == "10"

    async def test_no_params_sends_no_query(self, cloud_server):
        async with SolarAssistantClient("key", base_url=cloud_server.url) as client:
            await list_sites(client)
        assert cloud_server.last_request.query == {}


class TestTransport:
    async def test_sends_bearer_authorization_header(self, cloud_server):
        async with SolarAssistantClient("secret-key", base_url=cloud_server.url) as client:
            await list_sites(client)
        assert cloud_server.last_request.headers["Authorization"] == "Bearer secret-key"

    async def test_get_hits_sites_path(self, cloud_server):
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            await list_sites(client)
        assert cloud_server.last_request.method == "GET"
        assert cloud_server.last_request.path == "/api/v1/sites"

    async def test_trailing_slash_in_base_url_is_stripped(self, cloud_server):
        async with SolarAssistantClient("k", base_url=cloud_server.url + "/") as client:
            await list_sites(client)
        assert cloud_server.last_request.path == "/api/v1/sites"


class TestListSites:
    async def test_parses_site_with_owner(self, cloud_server):
        cloud_server.cfg.sites = [
            {
                "id": 1,
                "name": "Home",
                "inverter": "srne",
                "inverter_count": 2,
                "owner": {"id": 9, "email": "a@b.c", "first_name": "Ann", "last_name": "Lee"},
            }
        ]
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            sites = await list_sites(client)
        assert len(sites) == 1
        site = sites[0]
        assert isinstance(site, Site)
        assert site.id == 1
        assert site.name == "Home"
        assert site.inverter == "srne"
        assert site.inverter_count == 2
        assert site.owner.email == "a@b.c"
        assert site.owner.first_name == "Ann"

    async def test_missing_fields_get_defaults(self, cloud_server):
        cloud_server.cfg.sites = [{"id": 5}]
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            sites = await list_sites(client)
        site = sites[0]
        assert site.name == ""
        assert site.inverter_params == {}
        assert site.battery_count == 0
        assert site.beta is False
        assert site.owner.id == 0  # owner absent -> default SiteOwner

    async def test_null_params_coerced_to_empty_dict(self, cloud_server):
        cloud_server.cfg.sites = [{"id": 1, "inverter_params": None, "battery_params": None}]
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            sites = await list_sites(client)
        assert sites[0].inverter_params == {}
        assert sites[0].battery_params == {}

    async def test_empty_list(self, cloud_server):
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            sites = await list_sites(client)
        assert sites == []

    async def test_parses_multiple_sites(self, cloud_server):
        cloud_server.cfg.sites = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            sites = await list_sites(client)
        assert [s.name for s in sites] == ["A", "B"]


class TestAuthorizeSite:
    async def test_posts_and_parses_response(self, cloud_server):
        cloud_server.cfg.authorize = {
            "host": "proxy.example",
            "site_id": 7,
            "site_name": "Home",
            "site_key": "abc",
            "token": "jwt",
            "local_ip": "192.168.1.5",
        }
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            auth = await authorize_site(client, 7)
        assert isinstance(auth, AuthorizeResponse)
        assert auth.host == "proxy.example"
        assert auth.site_id == 7
        assert auth.site_key == "abc"
        assert auth.token == "jwt"
        assert auth.local_ip == "192.168.1.5"

    async def test_posts_to_authorize_path(self, cloud_server):
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            await authorize_site(client, 7)
        request = cloud_server.last_request
        assert request.method == "POST"
        assert request.path == "/api/v1/sites/7/authorize"
        assert request.headers["Authorization"] == "Bearer k"

    async def test_defaults_when_fields_absent(self, cloud_server):
        cloud_server.cfg.authorize = {}
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            auth = await authorize_site(client, 1)
        assert auth.host == ""
        assert auth.site_id == 0
        assert auth.token == ""


class TestErrors:
    async def test_non_200_raises_with_status(self, cloud_server):
        cloud_server.cfg.status = 403
        cloud_server.cfg.error_body = "forbidden"
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            with pytest.raises(SolarAssistantError) as excinfo:
                await list_sites(client)
        assert excinfo.value.status == 403

    async def test_authorize_error_propagates(self, cloud_server):
        cloud_server.cfg.status = 404
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            with pytest.raises(SolarAssistantError) as excinfo:
                await authorize_site(client, 99)
        assert excinfo.value.status == 404

    async def test_message_carries_endpoint_not_body(self, cloud_server):
        # The message is method + endpoint + status, never the response body -
        # not even a credential in free text, which key-based redaction couldn't
        # scrub. That's why the body is dropped wholesale rather than filtered.
        cloud_server.cfg.status = 400
        cloud_server.cfg.error_body = {"error": "denied for token=leakme"}
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            with pytest.raises(SolarAssistantError) as excinfo:
                await list_sites(client)
        msg = str(excinfo.value)
        assert excinfo.value.status == 400
        assert "GET" in msg and "/api/v1/sites" in msg  # useful diagnostics kept
        assert "leakme" not in msg and "denied" not in msg  # nothing from the body

    async def test_error_message_includes_query(self, cloud_server):
        # The query identifies which request failed; it's folded into the
        # endpoint so two searches don't render identical error text.
        cloud_server.cfg.status = 500
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            with pytest.raises(SolarAssistantError) as excinfo:
                await list_sites(client, search="boom")
        assert "q=boom" in str(excinfo.value)


class TestSessionOwnership:
    async def test_reuses_session_across_calls_in_context(self, cloud_server):
        async with SolarAssistantClient("k", base_url=cloud_server.url) as client:
            await list_sites(client)
            await list_sites(client)
        assert len(cloud_server.requests) == 2

    async def test_works_without_context_manager(self, cloud_server):
        # No ``async with``: each call creates and closes its own session.
        # filterwarnings=error fails the test if that per-call session leaks.
        client = SolarAssistantClient("k", base_url=cloud_server.url)
        sites = await list_sites(client)
        assert sites == []
        await client.close()  # no-op when no session was retained


class TestVerboseRedaction:
    async def test_credentials_are_redacted_in_debug_log(self, cloud_server, caplog):
        cloud_server.cfg.authorize = {"token": "supersecret", "site_key": "topsecret", "host": "h"}
        with caplog.at_level(logging.DEBUG, logger="py_solar_assistant.cloud"):
            async with SolarAssistantClient("k", base_url=cloud_server.url, verbose=True) as client:
                await authorize_site(client, 1)
        assert "[REDACTED]" in caplog.text
        assert "supersecret" not in caplog.text
        assert "topsecret" not in caplog.text
