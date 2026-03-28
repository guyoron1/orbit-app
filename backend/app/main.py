"""
Orbit API — Relationship Intelligence Backend

Endpoints:
  POST   /users                    Create a user
  POST   /contacts                 Add a contact to your orbit
  GET    /contacts                 List all contacts with health scores
  POST   /interactions             Log an interaction (triggers weight learning)
  GET    /contacts/{id}/health     Get detailed health report for a contact
  GET    /contacts/{id}/weights    View learned weights (transparency)
  POST   /life-events              Add a life event
  GET    /dashboard                Full dashboard data (stats + nudges + health)
  POST   /nudges/{id}/act          Mark a nudge as acted on
  POST   /nudges/{id}/snooze       Snooze a nudge
"""

from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from .database import Base, engine, get_db
from .models import (
    User, Contact, Interaction, Weights, Nudge, LifeEvent,
    NudgeStatus, INTERACTION_DEPTH,
)
from .schemas import (
    UserCreate, UserOut,
    ContactCreate, ContactOut,
    InteractionCreate, InteractionOut,
    HealthReportOut, WeightsOut,
    LifeEventCreate, LifeEventOut,
    NudgeOut, DashboardOut,
)
from .decay import compute_health, update_weights_after_interaction


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Orbit API",
    description="Relationship Intelligence Backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In a real app this comes from auth. For the prototype, we use a query param.
def get_current_user_id() -> int:
    return 1


# ── Users ──

@app.post("/users", response_model=UserOut)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(400, "Email already registered")
    user = User(email=data.email, name=data.name, timezone=data.timezone)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── Contacts ──

@app.post("/contacts", response_model=ContactOut)
def create_contact(
    data: ContactCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    contact = Contact(
        user_id=user_id,
        name=data.name,
        relationship_type=data.relationship_type,
        target_frequency=data.target_frequency,
        notes=data.notes,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)

    # Initialize weights with defaults
    weights = Weights(contact_id=contact.id)
    db.add(weights)
    db.commit()

    return contact


@app.get("/contacts", response_model=list[ContactOut])
def list_contacts(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    return db.query(Contact).filter(Contact.user_id == user_id).all()


# ── Interactions ──

@app.post("/interactions", response_model=InteractionOut)
def log_interaction(
    data: InteractionCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    contact = db.query(Contact).filter(
        Contact.id == data.contact_id, Contact.user_id == user_id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    # Compute quality score from interaction type + duration
    depth = INTERACTION_DEPTH.get(data.interaction_type, 0.3)
    duration_factor = min(1.0, data.duration_minutes / 60.0) if data.duration_minutes > 0 else 0.5
    quality = depth * 0.6 + duration_factor * 0.4

    interaction = Interaction(
        user_id=user_id,
        contact_id=data.contact_id,
        interaction_type=data.interaction_type,
        duration_minutes=data.duration_minutes,
        initiated_by_user=data.initiated_by_user,
        notes=data.notes,
        quality_score=round(quality, 3),
        timestamp=datetime.utcnow(),
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    # ── LEARNING STEP: update weights based on this new interaction ──
    update_weights_after_interaction(contact, interaction, db)

    return interaction


# ── Recent Interactions (for activity timeline) ──

@app.get("/interactions", response_model=list[InteractionOut])
def list_interactions(
    limit: int = 20,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    rows = (
        db.query(Interaction)
        .filter(Interaction.user_id == user_id)
        .order_by(Interaction.timestamp.desc())
        .limit(limit)
        .all()
    )
    return rows


# ── Health ──

@app.get("/contacts/{contact_id}/health", response_model=HealthReportOut)
def get_health(
    contact_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.user_id == user_id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")
    return compute_health(contact, db)


@app.get("/contacts/{contact_id}/weights", response_model=WeightsOut)
def get_weights(
    contact_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.user_id == user_id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")
    if not contact.weights:
        raise HTTPException(404, "No learned weights yet")
    return contact.weights


# ── Life Events ──

@app.post("/life-events", response_model=LifeEventOut)
def create_life_event(
    data: LifeEventCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    contact = db.query(Contact).filter(
        Contact.id == data.contact_id, Contact.user_id == user_id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    event = LifeEvent(
        contact_id=data.contact_id,
        event_type=data.event_type,
        description=data.description,
        event_date=data.event_date,
        pause_decay=data.pause_decay,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# ── Nudges ──

@app.post("/nudges/{nudge_id}/act")
def act_on_nudge(nudge_id: int, db: Session = Depends(get_db)):
    nudge = db.query(Nudge).filter(Nudge.id == nudge_id).first()
    if not nudge:
        raise HTTPException(404, "Nudge not found")
    nudge.status = NudgeStatus.acted
    nudge.acted_at = datetime.utcnow()
    db.commit()
    return {"status": "acted", "nudge_id": nudge_id}


@app.post("/nudges/{nudge_id}/snooze")
def snooze_nudge(nudge_id: int, db: Session = Depends(get_db)):
    nudge = db.query(Nudge).filter(Nudge.id == nudge_id).first()
    if not nudge:
        raise HTTPException(404, "Nudge not found")
    nudge.status = NudgeStatus.snoozed
    db.commit()
    return {"status": "snoozed", "nudge_id": nudge_id}


# ── Dashboard ──

@app.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    contacts_list = db.query(Contact).filter(Contact.user_id == user_id).all()
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    # Compute health for all contacts
    reports = [compute_health(c, db, now) for c in contacts_list]

    # Stats
    inner_circle = [r for r in reports if r.health >= 75]
    avg_health = sum(r.health for r in reports) / len(reports) if reports else 0

    interactions_week = (
        db.query(func.count(Interaction.id))
        .filter(
            Interaction.user_id == user_id,
            Interaction.timestamp >= week_ago,
        )
        .scalar() or 0
    )

    # Generate nudges for contacts that need attention
    nudge_reports = sorted(reports, key=lambda r: r.urgency, reverse=True)
    top_nudges = []
    for r in nudge_reports[:5]:
        if r.urgency > 0.2:
            # Check if there's already a pending nudge for this contact
            existing = db.query(Nudge).filter(
                Nudge.contact_id == r.contact_id,
                Nudge.status == NudgeStatus.pending,
            ).first()

            if not existing:
                nudge = Nudge(
                    user_id=user_id,
                    contact_id=r.contact_id,
                    message=f"It's been {r.days_since_contact:.0f} days since you talked to {r.contact_name}",
                    suggestion=r.suggested_action,
                    priority=r.urgency,
                )
                db.add(nudge)
                db.commit()
                db.refresh(nudge)
                existing = nudge

            top_nudges.append(NudgeOut(
                id=existing.id,
                contact_id=existing.contact_id,
                contact_name=r.contact_name,
                message=existing.message,
                suggestion=existing.suggestion,
                priority=existing.priority,
                status=existing.status.value,
                created_at=existing.created_at,
            ))

    return DashboardOut(
        total_contacts=len(contacts_list),
        inner_circle_count=len(inner_circle),
        avg_health=round(avg_health, 1),
        interactions_this_week=interactions_week,
        health_reports=reports,
        top_nudges=top_nudges,
    )


# ── Frontend ──

FRONTEND_PATH = Path(__file__).resolve().parent.parent.parent / "index.html"


@app.get("/", response_class=FileResponse)
def serve_frontend():
    return FileResponse(FRONTEND_PATH, media_type="text/html")
