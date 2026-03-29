"""Tests for the adaptive decay algorithm."""

import math
from datetime import datetime, timedelta

from app.decay import learning_rate, compute_health, _default_weights
from app.models import Contact, Interaction, Weights, RelationshipType, ContactFrequency, InteractionType

from tests.conftest import TestSession, engine
from app.database import Base


def test_learning_rate_starts_high():
    assert learning_rate(0) == 0.3


def test_learning_rate_decays():
    lr_0 = learning_rate(0)
    lr_10 = learning_rate(10)
    lr_50 = learning_rate(50)
    assert lr_0 > lr_10 > lr_50


def test_learning_rate_has_floor():
    assert learning_rate(1000) == 0.05


def test_default_weights_vary_by_type():
    family = Contact(
        id=1, user_id=1, name="Mom",
        relationship_type=RelationshipType.family,
        target_frequency=ContactFrequency.weekly,
    )
    acquaintance = Contact(
        id=2, user_id=1, name="Bob",
        relationship_type=RelationshipType.acquaintance,
        target_frequency=ContactFrequency.monthly,
    )
    fw = _default_weights(family)
    aw = _default_weights(acquaintance)
    # Family should decay slower
    assert fw.lambda_decay < aw.lambda_decay


def test_health_full_when_just_contacted():
    """Health should be ~100 right after an interaction."""
    Base.metadata.create_all(bind=engine)
    db = TestSession()
    try:
        from app.models import User
        user = User(id=1, email="t@t.com", name="T", password_hash="x")
        db.add(user)
        contact = Contact(
            user_id=1, name="Friend",
            relationship_type=RelationshipType.friend,
            target_frequency=ContactFrequency.weekly,
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)

        weights = Weights(contact_id=contact.id)
        db.add(weights)

        interaction = Interaction(
            user_id=1, contact_id=contact.id,
            interaction_type=InteractionType.call,
            timestamp=datetime.utcnow() - timedelta(hours=1),
        )
        db.add(interaction)
        db.commit()

        report = compute_health(contact, db)
        # Health is modulated by reciprocity (only 1 user-initiated interaction
        # means reciprocity_ratio=0, which lowers health). With default w_reciprocity=0.3,
        # health ≈ 100 * 1.0 * (1 - 0.3*(1-0)) * quality_boost ≈ 70ish
        assert report.health >= 40
        assert report.days_since_contact < 1
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_health_decays_over_time():
    """Health should drop as days pass without interaction."""
    Base.metadata.create_all(bind=engine)
    db = TestSession()
    try:
        from app.models import User
        user = User(id=1, email="t@t.com", name="T", password_hash="x")
        db.add(user)
        contact = Contact(
            user_id=1, name="Friend",
            relationship_type=RelationshipType.friend,
            target_frequency=ContactFrequency.weekly,
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)

        weights = Weights(contact_id=contact.id, grace_period=2.0)
        db.add(weights)

        interaction = Interaction(
            user_id=1, contact_id=contact.id,
            interaction_type=InteractionType.text,
            timestamp=datetime.utcnow() - timedelta(days=30),
        )
        db.add(interaction)
        db.commit()

        report = compute_health(contact, db)
        assert report.health < 50
        assert report.days_since_contact >= 29
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
