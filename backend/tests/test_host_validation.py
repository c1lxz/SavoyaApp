from __future__ import annotations

from backend.app.main import _is_allowed_host


def test_allowed_domain_host_is_accepted(client) -> None:
    response = client.get("/health", headers={"host": "ipksavoya.ru"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_allowed_host_with_port_is_accepted(client) -> None:
    response = client.get("/health", headers={"host": "ipksavoya.ru:443"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unallowed_host_is_rejected(client) -> None:
    response = client.get("/health", headers={"host": "evil.example.com"})

    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_host_matcher_accepts_www_alias() -> None:
    assert _is_allowed_host("www.ipksavoya.ru")
