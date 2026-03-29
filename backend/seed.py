"""
Seed the database with realistic demo data.
Creates a user, 12 contacts, and interaction histories so the
decay algorithm has real data to learn from.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timedelta
import random

from app.database import Base, engine, SessionLocal
from app.models import (
    User, Contact, Interaction, Weights, LifeEvent,
    RelationshipType, ContactFrequency, InteractionType, LifeEventType,
)
from app.decay import update_weights_after_interaction


def seed():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    now = datetime.utcnow()

    # ── User ──
    from app.auth import hash_password
    user = User(
        id=1,
        email="jordan@example.com",
        password_hash=hash_password("orbit2024demo"),
        name="Jordan Davis",
        plan="pro",
    )
    db.add(user)
    db.commit()

    # ── Contacts ──
    contacts_data = [
        ("Sarah Chen", RelationshipType.friend, ContactFrequency.weekly, "Best friend, designer at Figma, loves hiking, adopted a cat named Pixel"),
        ("Marcus Williams", RelationshipType.friend, ContactFrequency.biweekly, "College roommate, PM at Google, expecting first child in April"),
        ("Mom", RelationshipType.family, ContactFrequency.weekly, "Book club Thursdays, planning garden for spring"),
        ("Alex Rivera", RelationshipType.work, ContactFrequency.monthly, "Ex-colleague, just joined Stripe, into rock climbing"),
        ("Emma Kim", RelationshipType.family, ContactFrequency.weekly, "Sister, finishing grad school in May, loves Korean BBQ"),
        ("David Park", RelationshipType.mentor, ContactFrequency.monthly, "VP Eng at Datadog, career mentor, offered to review resume"),
        ("Priya Patel", RelationshipType.friend, ContactFrequency.biweekly, "Yoga class friend, training for marathon, vegetarian"),
        ("James O'Brien", RelationshipType.friend, ContactFrequency.monthly, "Neighbor, has spare key, loves craft beer"),
        ("Lisa Zhang", RelationshipType.work, ContactFrequency.weekly, "Business partner, side project collaborator, great with React"),
        ("Dad", RelationshipType.family, ContactFrequency.weekly, "Retirement party coming up, wants to learn golf"),
        ("Tomoko Sato", RelationshipType.friend, ContactFrequency.monthly, "College friend, lives in Tokyo, works at Sony"),
        ("Ryan Cooper", RelationshipType.friend, ContactFrequency.biweekly, "Gym buddy, deadlift PR last week, starting a podcast"),
    ]

    contact_objs = []
    for name, rel_type, freq, notes in contacts_data:
        c = Contact(
            user_id=1,
            name=name,
            relationship_type=rel_type,
            target_frequency=freq,
            notes=notes,
            created_at=now - timedelta(days=random.randint(60, 365)),
        )
        db.add(c)
        db.commit()
        db.refresh(c)

        # Initialize weights
        w = Weights(contact_id=c.id)
        db.add(w)
        db.commit()

        contact_objs.append(c)

    # ── Interaction histories ──
    # Each contact gets a realistic history of past interactions.
    # The pattern varies: some contacts are consistent, some have gaps.

    interaction_patterns = {
        "Sarah Chen": {
            "types": [InteractionType.call, InteractionType.text, InteractionType.in_person, InteractionType.video_call],
            "avg_gap_days": 5, "gap_variance": 2, "count": 25, "reciprocity": 0.45,
        },
        "Marcus Williams": {
            "types": [InteractionType.text, InteractionType.call, InteractionType.social_media],
            "avg_gap_days": 10, "gap_variance": 5, "count": 15, "reciprocity": 0.4,
        },
        "Mom": {
            "types": [InteractionType.call, InteractionType.video_call, InteractionType.in_person],
            "avg_gap_days": 7, "gap_variance": 3, "count": 20, "reciprocity": 0.5,
        },
        "Alex Rivera": {
            "types": [InteractionType.text, InteractionType.social_media],
            "avg_gap_days": 25, "gap_variance": 10, "count": 6, "reciprocity": 0.3,
        },
        "Emma Kim": {
            "types": [InteractionType.text, InteractionType.call, InteractionType.in_person],
            "avg_gap_days": 4, "gap_variance": 2, "count": 30, "reciprocity": 0.55,
        },
        "David Park": {
            "types": [InteractionType.call, InteractionType.email, InteractionType.in_person],
            "avg_gap_days": 20, "gap_variance": 8, "count": 8, "reciprocity": 0.35,
        },
        "Priya Patel": {
            "types": [InteractionType.in_person, InteractionType.text],
            "avg_gap_days": 12, "gap_variance": 6, "count": 10, "reciprocity": 0.4,
        },
        "James O'Brien": {
            "types": [InteractionType.in_person, InteractionType.text],
            "avg_gap_days": 15, "gap_variance": 5, "count": 9, "reciprocity": 0.5,
        },
        "Lisa Zhang": {
            "types": [InteractionType.text, InteractionType.video_call, InteractionType.call],
            "avg_gap_days": 3, "gap_variance": 1, "count": 35, "reciprocity": 0.5,
        },
        "Dad": {
            "types": [InteractionType.call, InteractionType.in_person],
            "avg_gap_days": 9, "gap_variance": 4, "count": 14, "reciprocity": 0.45,
        },
        "Tomoko Sato": {
            "types": [InteractionType.social_media, InteractionType.text],
            "avg_gap_days": 30, "gap_variance": 15, "count": 5, "reciprocity": 0.2,
        },
        "Ryan Cooper": {
            "types": [InteractionType.in_person, InteractionType.text],
            "avg_gap_days": 8, "gap_variance": 4, "count": 12, "reciprocity": 0.5,
        },
    }

    for contact in contact_objs:
        pattern = interaction_patterns.get(contact.name)
        if not pattern:
            continue

        # Generate interactions going back in time
        ts = now
        for i in range(pattern["count"]):
            gap = max(1, pattern["avg_gap_days"] + random.randint(-pattern["gap_variance"], pattern["gap_variance"]))
            ts = ts - timedelta(days=gap, hours=random.randint(0, 12))

            itype = random.choice(pattern["types"])
            by_user = random.random() > pattern["reciprocity"]
            duration = random.randint(5, 60) if itype in (InteractionType.call, InteractionType.video_call, InteractionType.in_person) else 0

            interaction = Interaction(
                user_id=1,
                contact_id=contact.id,
                interaction_type=itype,
                duration_minutes=duration,
                initiated_by_user=by_user,
                quality_score=0.5,
                timestamp=ts,
            )
            db.add(interaction)
            db.commit()
            db.refresh(interaction)

        # Now replay the last 10 interactions in chronological order
        # to train the weights (the learning loop)
        recent = (
            db.query(Interaction)
            .filter(Interaction.contact_id == contact.id)
            .order_by(Interaction.timestamp.asc())
            .limit(10)
            .all()
        )

        # Refresh the contact to pick up the weights relationship
        db.refresh(contact)
        for inter in recent:
            update_weights_after_interaction(contact, inter, db)

    # ── Life Events ──
    events = [
        (contact_objs[1], LifeEventType.baby, "Expecting first child", now + timedelta(days=30), True),
        (contact_objs[9], LifeEventType.custom, "Retirement party", now + timedelta(days=14), False),
        (contact_objs[4], LifeEventType.graduation, "Finishing grad school", now + timedelta(days=60), False),
        (contact_objs[3], LifeEventType.job_change, "Started at Stripe", now - timedelta(days=21), True),
    ]
    for contact, etype, desc, edate, pause in events:
        db.add(LifeEvent(
            contact_id=contact.id,
            event_type=etype,
            description=desc,
            event_date=edate,
            pause_decay=pause,
        ))

    db.commit()
    db.close()
    print("Database seeded successfully!")
    print(f"  - 1 user")
    print(f"  - {len(contacts_data)} contacts")
    print(f"  - ~189 interactions with learned weights")
    print(f"  - {len(events)} life events")


if __name__ == "__main__":
    seed()
