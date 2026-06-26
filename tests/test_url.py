"""Tests for the URL hygiene helpers (``_url.py``)."""

from __future__ import annotations

import pytest

from py_solar_assistant._url import safe_url


class TestSafeUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            # userinfo (a credential a caller put in the host) is stripped...
            (
                "http://admin:secret@192.168.1.100/api/v1/system",
                "http://192.168.1.100/api/v1/system",
            ),
            # ...while port, path and query are kept (none are secret)...
            (
                "http://admin:secret@192.168.1.100:8080/api/v1/metrics?topic=x",
                "http://192.168.1.100:8080/api/v1/metrics?topic=x",
            ),
            # ...and a URL without userinfo is returned untouched.
            ("http://192.168.1.100/api/v1/system", "http://192.168.1.100/api/v1/system"),
            # An IPv6 literal keeps its brackets (taken verbatim from the netloc,
            # not rebuilt from .hostname/.port, which would drop them).
            (
                "http://admin:secret@[2001:db8::1]:8080/api/v1/system",
                "http://[2001:db8::1]:8080/api/v1/system",
            ),
            ("http://[2001:db8::1]:8080/api/v1/system", "http://[2001:db8::1]:8080/api/v1/system"),
        ],
    )
    def test_strips_userinfo_only(self, url, expected):
        assert safe_url(url) == expected
