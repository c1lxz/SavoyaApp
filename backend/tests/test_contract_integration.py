from __future__ import annotations


def test_compat_login_success(client):
    response = client.post("/auth/login", json={"login": "demo", "password": "demo123"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["user"]["login"] == "demo"
    assert isinstance(data["access_token"], str)


def test_compat_login_failure(client):
    response = client.post("/auth/login", json={"login": "demo", "password": "wrong"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "Invalid login or password"


def test_passes_create_and_list(client):
    login = client.post("/auth/login", json={"login": "demo", "password": "demo123"}).json()
    token = login["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/passes",
        headers=headers,
        json={
            "carNumber": "A123BB",
            "plotNumber": "25",
            "expiresAt": None,
            "isPermanent": True,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["status"] == "permanent"

    list_response = client.get("/passes/my", headers=headers)
    assert list_response.status_code == 200
    rows = list_response.json()
    assert len(rows) >= 1
    assert any(item["carNumber"] == "A123BB" for item in rows)


def test_gate_open_action(client):
    login = client.post("/auth/login", json={"login": "demo", "password": "demo123"}).json()
    token = login["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        "/passes",
        headers=headers,
        json={"carNumber": "B234CC", "plotNumber": "25", "expiresAt": None, "isPermanent": True},
    )
    response = client.post("/gates/open-action", headers=headers, json={"action": "entry"})
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "entry"
    assert "success" in data
