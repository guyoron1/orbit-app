"""Tests for authentication endpoints."""


def test_signup_success(client):
    resp = client.post("/auth/signup", json={
        "email": "new@orbit.app",
        "password": "password123",
        "name": "New User",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "new@orbit.app"
    assert data["user"]["name"] == "New User"


def test_signup_duplicate_email(client):
    client.post("/auth/signup", json={
        "email": "dup@orbit.app",
        "password": "password123",
        "name": "First",
    })
    resp = client.post("/auth/signup", json={
        "email": "dup@orbit.app",
        "password": "password456",
        "name": "Second",
    })
    assert resp.status_code == 400


def test_signup_short_password(client):
    resp = client.post("/auth/signup", json={
        "email": "short@orbit.app",
        "password": "abc",
        "name": "Short Pass",
    })
    assert resp.status_code == 422  # Pydantic validation


def test_login_success(client):
    client.post("/auth/signup", json={
        "email": "login@orbit.app",
        "password": "password123",
        "name": "Login User",
    })
    resp = client.post("/auth/login", json={
        "email": "login@orbit.app",
        "password": "password123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password(client):
    client.post("/auth/signup", json={
        "email": "wrong@orbit.app",
        "password": "password123",
        "name": "Wrong Pass",
    })
    resp = client.post("/auth/login", json={
        "email": "wrong@orbit.app",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_protected_route_without_token(client):
    resp = client.get("/contacts")
    assert resp.status_code == 401


def test_protected_route_with_token(auth_client):
    resp = auth_client.get("/contacts")
    assert resp.status_code == 200
    assert resp.json() == []
