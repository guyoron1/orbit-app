"""Tests for API endpoints."""


def test_create_contact(auth_client):
    resp = auth_client.post("/contacts", json={
        "name": "Alice Smith",
        "relationship_type": "friend",
        "target_frequency": "weekly",
        "notes": "Met at a conference",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Alice Smith"
    assert data["relationship_type"] == "friend"


def test_list_contacts_empty(auth_client):
    resp = auth_client.get("/contacts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_contacts_after_create(auth_client):
    auth_client.post("/contacts", json={
        "name": "Bob Jones",
        "relationship_type": "work",
    })
    resp = auth_client.get("/contacts")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_log_interaction(auth_client):
    # Create contact first
    contact = auth_client.post("/contacts", json={
        "name": "Carol Davis",
        "relationship_type": "friend",
    }).json()

    resp = auth_client.post("/interactions", json={
        "contact_id": contact["id"],
        "interaction_type": "call",
        "duration_minutes": 30,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["interaction_type"] == "call"
    assert data["quality_score"] > 0


def test_interaction_invalid_contact(auth_client):
    resp = auth_client.post("/interactions", json={
        "contact_id": 9999,
        "interaction_type": "call",
    })
    assert resp.status_code == 404


def test_dashboard(auth_client):
    # Create a contact
    auth_client.post("/contacts", json={
        "name": "Dan Lee",
        "relationship_type": "mentor",
    })
    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_contacts"] == 1
    assert len(data["health_reports"]) == 1


def test_contact_health(auth_client):
    contact = auth_client.post("/contacts", json={
        "name": "Eve Park",
        "relationship_type": "family",
    }).json()

    resp = auth_client.get(f"/contacts/{contact['id']}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "health" in data
    assert "urgency" in data
    assert "trend" in data


def test_contact_name_too_long(auth_client):
    resp = auth_client.post("/contacts", json={
        "name": "A" * 300,
        "relationship_type": "friend",
    })
    assert resp.status_code == 422


def test_notes_too_long(auth_client):
    resp = auth_client.post("/contacts", json={
        "name": "Normal Name",
        "relationship_type": "friend",
        "notes": "x" * 3000,
    })
    assert resp.status_code == 422


def test_interaction_duration_negative(auth_client):
    contact = auth_client.post("/contacts", json={
        "name": "Test",
        "relationship_type": "friend",
    }).json()
    resp = auth_client.post("/interactions", json={
        "contact_id": contact["id"],
        "interaction_type": "call",
        "duration_minutes": -5,
    })
    assert resp.status_code == 422
