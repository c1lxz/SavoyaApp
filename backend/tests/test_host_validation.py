from __future__ import annotations

from backend.app.main import _is_allowed_host


def test_allowed_punycode_host_is_accepted(client) -> None:
    response = client.get("/health", headers={"host": "xn--80aaachc8cmu1au8c1f.xn--p1ai"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_allowed_host_with_port_is_accepted(client) -> None:
    response = client.get("/health", headers={"host": "xn--80aaachc8cmu1au8c1f.xn--p1ai:443"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unallowed_host_is_rejected(client) -> None:
    response = client.get("/health", headers={"host": "evil.example.com"})

    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_host_matcher_supports_unicode_alias_for_punycode_domain() -> None:
    assert _is_allowed_host("\u0448\u043b\u0430\u0433\u0431\u0430\u0443\u043c\u0441\u0430\u0432\u043e\u044f.\u0440\u0444")
