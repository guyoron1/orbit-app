"""Shared test fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app, limiter


TEST_DB_URL = "sqlite:///./test.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh tables for each test and disable rate limiting."""
    Base.metadata.create_all(bind=engine)
    limiter.enabled = False
    yield
    limiter.enabled = True
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_client(client):
    """Client with a logged-in user."""
    # Create user
    resp = client.post("/auth/signup", json={
        "email": "test@orbit.app",
        "password": "testpass123",
        "name": "Test User",
    })
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    # Return client with auth header helper
    class AuthClient:
        def __init__(self, client, token):
            self._client = client
            self._token = token
            self._headers = {"Authorization": f"Bearer {token}"}

        def get(self, url, **kwargs):
            kwargs.setdefault("headers", {}).update(self._headers)
            return self._client.get(url, **kwargs)

        def post(self, url, **kwargs):
            kwargs.setdefault("headers", {}).update(self._headers)
            return self._client.post(url, **kwargs)

    return AuthClient(client, token)
