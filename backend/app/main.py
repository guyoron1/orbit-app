"""
Orbit API — Relationship Intelligence Backend

Auth endpoints:
  POST   /auth/signup              Create account
  POST   /auth/login               Login, get JWT token

Protected endpoints (require Bearer token):
  POST   /contacts                 Add a contact to your orbit
  GET    /contacts                 List all contacts with health scores
  POST   /interactions             Log an interaction (triggers weight learning)
  GET    /interactions             Recent interactions timeline
  GET    /contacts/{id}/health     Detailed health report for a contact
  GET    /contacts/{id}/weights    View learned weights (transparency)
  GET    /contacts/{id}/starters   AI conversation starters
  POST   /life-events              Add a life event
  GET    /dashboard                Full dashboard data (stats + nudges + health + AI summary)
  POST   /nudges/{id}/act          Mark a nudge as acted on
  POST   /nudges/{id}/snooze       Snooze a nudge
"""

import os
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

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
    SignupRequest, LoginRequest, TokenResponse,
    ConversationStartersOut, AISummaryOut,
)
from .decay import compute_health, update_weights_after_interaction
from .auth import hash_password, verify_password, create_access_token, get_current_user
from .ai import generate_conversation_starters, generate_relationship_summary


# ── Rate limiter ──
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Orbit API",
    description="Relationship Intelligence Backend",
    version="0.2.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ── Security headers middleware ──
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ══════════════════════════════════════════════
# AUTH ENDPOINTS (public)
# ══════════════════════════════════════════════

@app.post("/auth/signup", response_model=TokenResponse)
@limiter.limit("5/minute")
def signup(request: Request, data: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(400, "Email already registered")

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        name=data.name,
        timezone=data.timezone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.email)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@app.post("/auth/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")

    token = create_access_token(user.id, user.email)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


# ══════════════════════════════════════════════
# CONTACTS (protected)
# ══════════════════════════════════════════════

@app.post("/contacts", response_model=ContactOut)
@limiter.limit("30/minute")
def create_contact(
    request: Request,
    data: ContactCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Free plan limit: 25 contacts
    count = db.query(func.count(Contact.id)).filter(Contact.user_id == user.id).scalar() or 0
    if user.plan == "free" and count >= 25:
        raise HTTPException(403, "Free plan limited to 25 contacts. Upgrade to Pro for unlimited.")

    contact = Contact(
        user_id=user.id,
        name=data.name,
        relationship_type=data.relationship_type,
        target_frequency=data.target_frequency,
        notes=data.notes,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)

    weights = Weights(contact_id=contact.id)
    db.add(weights)
    db.commit()

    return contact


@app.get("/contacts", response_model=list[ContactOut])
def list_contacts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return db.query(Contact).filter(Contact.user_id == user.id).all()


# ══════════════════════════════════════════════
# INTERACTIONS (protected)
# ══════════════════════════════════════════════

@app.post("/interactions", response_model=InteractionOut)
@limiter.limit("60/minute")
def log_interaction(
    request: Request,
    data: InteractionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = db.query(Contact).filter(
        Contact.id == data.contact_id, Contact.user_id == user.id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    depth = INTERACTION_DEPTH.get(data.interaction_type, 0.3)
    duration_factor = min(1.0, data.duration_minutes / 60.0) if data.duration_minutes > 0 else 0.5
    quality = depth * 0.6 + duration_factor * 0.4

    interaction = Interaction(
        user_id=user.id,
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

    update_weights_after_interaction(contact, interaction, db)

    return interaction


@app.get("/interactions", response_model=list[InteractionOut])
def list_interactions(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return (
        db.query(Interaction)
        .filter(Interaction.user_id == user.id)
        .order_by(Interaction.timestamp.desc())
        .limit(min(limit, 100))
        .all()
    )


# ══════════════════════════════════════════════
# HEALTH & WEIGHTS (protected)
# ══════════════════════════════════════════════

@app.get("/contacts/{contact_id}/health", response_model=HealthReportOut)
def get_health(
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.user_id == user.id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")
    return compute_health(contact, db)


@app.get("/contacts/{contact_id}/weights", response_model=WeightsOut)
def get_weights(
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.user_id == user.id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")
    if not contact.weights:
        raise HTTPException(404, "No learned weights yet")
    return contact.weights


# ══════════════════════════════════════════════
# AI ENDPOINTS (protected)
# ══════════════════════════════════════════════

@app.get("/contacts/{contact_id}/starters", response_model=ConversationStartersOut)
@limiter.limit("20/minute")
def get_conversation_starters(
    request: Request,
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.user_id == user.id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    health_report = compute_health(contact, db)

    # Get last interaction type
    last = (
        db.query(Interaction)
        .filter(Interaction.contact_id == contact_id)
        .order_by(Interaction.timestamp.desc())
        .first()
    )

    # Build recent interactions summary
    recent = (
        db.query(Interaction)
        .filter(Interaction.contact_id == contact_id)
        .order_by(Interaction.timestamp.desc())
        .limit(5)
        .all()
    )
    summary_parts = []
    for r in recent:
        days_ago = (datetime.utcnow() - r.timestamp).days
        summary_parts.append(f"{r.interaction_type.value} {days_ago} days ago")
    recent_summary = "; ".join(summary_parts) if summary_parts else "No recent interactions"

    starters = generate_conversation_starters(
        contact_name=contact.name,
        relationship_type=contact.relationship_type.value,
        notes=contact.notes,
        days_since_contact=health_report.days_since_contact,
        last_interaction_type=last.interaction_type.value if last else None,
        health=health_report.health,
        recent_interactions_summary=recent_summary,
    )

    return ConversationStartersOut(
        contact_id=contact.id,
        contact_name=contact.name,
        starters=starters,
    )


# ══════════════════════════════════════════════
# LIFE EVENTS (protected)
# ══════════════════════════════════════════════

@app.post("/life-events", response_model=LifeEventOut)
def create_life_event(
    data: LifeEventCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = db.query(Contact).filter(
        Contact.id == data.contact_id, Contact.user_id == user.id
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


# ══════════════════════════════════════════════
# NUDGES (protected)
# ══════════════════════════════════════════════

@app.post("/nudges/{nudge_id}/act")
def act_on_nudge(
    nudge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    nudge = db.query(Nudge).filter(
        Nudge.id == nudge_id, Nudge.user_id == user.id
    ).first()
    if not nudge:
        raise HTTPException(404, "Nudge not found")
    nudge.status = NudgeStatus.acted
    nudge.acted_at = datetime.utcnow()
    db.commit()
    return {"status": "acted", "nudge_id": nudge_id}


@app.post("/nudges/{nudge_id}/snooze")
def snooze_nudge(
    nudge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    nudge = db.query(Nudge).filter(
        Nudge.id == nudge_id, Nudge.user_id == user.id
    ).first()
    if not nudge:
        raise HTTPException(404, "Nudge not found")
    nudge.status = NudgeStatus.snoozed
    db.commit()
    return {"status": "snoozed", "nudge_id": nudge_id}


# ══════════════════════════════════════════════
# DASHBOARD (protected)
# ══════════════════════════════════════════════

@app.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contacts_list = db.query(Contact).filter(Contact.user_id == user.id).all()
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    reports = [compute_health(c, db, now) for c in contacts_list]

    inner_circle = [r for r in reports if r.health >= 75]
    avg_health = sum(r.health for r in reports) / len(reports) if reports else 0

    interactions_week = (
        db.query(func.count(Interaction.id))
        .filter(
            Interaction.user_id == user.id,
            Interaction.timestamp >= week_ago,
        )
        .scalar() or 0
    )

    # Generate nudges
    nudge_reports = sorted(reports, key=lambda r: r.urgency, reverse=True)
    top_nudges = []
    for r in nudge_reports[:5]:
        if r.urgency > 0.2:
            existing = db.query(Nudge).filter(
                Nudge.contact_id == r.contact_id,
                Nudge.status == NudgeStatus.pending,
            ).first()

            if not existing:
                nudge = Nudge(
                    user_id=user.id,
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

    # AI summary (non-blocking — falls back to static if no API key)
    ai_summary = generate_relationship_summary(
        contacts_data=[
            {"name": r.contact_name, "health": r.health, "trend": r.trend}
            for r in reports
        ],
        total_contacts=len(contacts_list),
        avg_health=round(avg_health, 1),
        interactions_this_week=interactions_week,
    )

    return DashboardOut(
        total_contacts=len(contacts_list),
        inner_circle_count=len(inner_circle),
        avg_health=round(avg_health, 1),
        interactions_this_week=interactions_week,
        health_reports=reports,
        top_nudges=top_nudges,
        ai_summary=ai_summary,
    )


# ══════════════════════════════════════════════
# FRONTEND (serves index.html at root if present)
# When deployed as monolith: index.html sits alongside backend/
# When API-only mode: returns JSON health check instead
# ══════════════════════════════════════════════

FRONTEND_PATH = Path(__file__).resolve().parent.parent.parent / "index.html"


@app.get("/")
def serve_frontend():
    if FRONTEND_PATH.exists():
        return FileResponse(FRONTEND_PATH, media_type="text/html")
    return {"status": "ok", "service": "Orbit API", "version": "0.3.0"}
