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
    User, Contact, Interaction, Weights, Nudge, LifeEvent, Quest,
    Party, PartyMember, Challenge, StravaConnection,
    NudgeStatus, QuestStatus, PartyStatus, ChallengeStatus, Recurrence,
    INTERACTION_DEPTH, FREQUENCY_DAYS,
)
from .schemas import (
    UserCreate, UserOut,
    ContactCreate, ContactUpdate, ContactOut,
    InteractionCreate, InteractionOut,
    HealthReportOut, WeightsOut,
    LifeEventCreate, LifeEventOut,
    NudgeOut, DashboardOut,
    SignupRequest, LoginRequest, TokenResponse,
    ConversationStartersOut, AISummaryOut,
    QuestOut, AchievementDef, XPAwardOut, LevelProgressOut,
    GamificationDashboardOut,
    PartyCreate, PartyOut, PartyMemberOut,
    ChallengeCreate, ChallengeOut,
    FeedItemOut, LeaderboardOut, LeaderboardEntryOut,
    NearbyContactOut, LocationUpdate, StravaStatusOut,
)
from .decay import compute_health, update_weights_after_interaction
from .auth import hash_password, verify_password, create_access_token, get_current_user
from .ai import generate_conversation_starters, generate_relationship_summary
from .gamification import (
    award_interaction_xp, generate_quests, complete_quest,
    level_progress, ACHIEVEMENT_DEFS,
)


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


@app.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: int,
    data: ContactUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.user_id == user.id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    db.commit()
    db.refresh(contact)
    return contact


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

    # Award gamification XP
    award_interaction_xp(user, contact, interaction, db)

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
# GAMIFICATION (protected)
# ══════════════════════════════════════════════

@app.get("/quests", response_model=list[QuestOut])
def list_quests(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Auto-generate quests if needed
    generate_quests(user, db)
    return (
        db.query(Quest)
        .filter(Quest.user_id == user.id, Quest.status == QuestStatus.active)
        .all()
    )


@app.post("/quests/{quest_id}/complete", response_model=XPAwardOut)
def complete_quest_endpoint(
    quest_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    quest = db.query(Quest).filter(
        Quest.id == quest_id, Quest.user_id == user.id,
        Quest.status == QuestStatus.active,
    ).first()
    if not quest:
        raise HTTPException(404, "Quest not found or already completed")

    result = complete_quest(quest, user, db)
    return XPAwardOut(
        xp_earned=result["xp_earned"],
        base_xp=result["xp_earned"],
        duration_bonus=0,
        new_level=result["new_level"],
        new_achievements=result["new_achievements"],
    )


@app.post("/quests/{quest_id}/skip")
def skip_quest(
    quest_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    quest = db.query(Quest).filter(
        Quest.id == quest_id, Quest.user_id == user.id,
        Quest.status == QuestStatus.active,
    ).first()
    if not quest:
        raise HTTPException(404, "Quest not found")
    quest.status = QuestStatus.skipped
    db.commit()
    return {"status": "skipped", "quest_id": quest_id}


@app.get("/achievements", response_model=list[AchievementDef])
def list_achievements(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from .models import UserAchievement
    earned = {
        ua.achievement_key: ua.earned_at
        for ua in db.query(UserAchievement).filter(UserAchievement.user_id == user.id).all()
    }
    return [
        AchievementDef(
            key=key, name=name, description=desc, icon=icon, xp_bonus=xp,
            earned=key in earned,
            earned_at=earned.get(key),
        )
        for key, name, desc, icon, xp in ACHIEVEMENT_DEFS
    ]


@app.get("/level", response_model=LevelProgressOut)
def get_level(user: User = Depends(get_current_user)):
    return LevelProgressOut(**level_progress(user.xp or 0))


# ══════════════════════════════════════════════
# PARTIES / HANGOUTS (protected)
# ══════════════════════════════════════════════

ACTIVITY_XP = {
    "run": 60, "gym": 55, "hike": 65, "concert": 50,
    "dinner": 45, "drinks": 40, "gaming": 35, "movie": 30,
    "sports": 60, "study": 35, "custom": 40,
}
GROUP_XP_MULTIPLIER = 1.5  # bonus for group activities


@app.post("/parties", response_model=PartyOut)
@limiter.limit("20/minute")
def create_party(
    request: Request,
    data: PartyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    base_xp = ACTIVITY_XP.get(data.activity_type.value, 40)

    party = Party(
        creator_id=user.id,
        title=data.title,
        activity_type=data.activity_type,
        description=data.description,
        location=data.location,
        scheduled_at=data.scheduled_at,
        xp_reward=base_xp,
        is_recurring=data.is_recurring,
        recurrence=data.recurrence,
    )
    db.add(party)
    db.commit()
    db.refresh(party)

    # Add invited contacts as members
    for cid in data.contact_ids:
        contact = db.query(Contact).filter(
            Contact.id == cid, Contact.user_id == user.id
        ).first()
        if contact:
            member = PartyMember(party_id=party.id, contact_id=cid, status="invited")
            db.add(member)
    db.commit()
    db.refresh(party)

    return _party_to_out(party, db)


@app.get("/parties", response_model=list[PartyOut])
def list_parties(
    status: str = "all",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Party).filter(Party.creator_id == user.id)
    if status == "waiting":
        q = q.filter(Party.status == PartyStatus.waiting)
    elif status == "active":
        q = q.filter(Party.status.in_([PartyStatus.waiting, PartyStatus.active]))
    q = q.order_by(Party.created_at.desc())
    return [_party_to_out(p, db) for p in q.limit(20).all()]


@app.post("/parties/{party_id}/start")
def start_party(
    party_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    party = db.query(Party).filter(
        Party.id == party_id, Party.creator_id == user.id,
        Party.status == PartyStatus.waiting,
    ).first()
    if not party:
        raise HTTPException(404, "Party not found or already started")
    party.status = PartyStatus.active
    db.commit()
    return {"status": "active", "party_id": party_id}


@app.post("/parties/{party_id}/complete")
def complete_party(
    party_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    party = db.query(Party).filter(
        Party.id == party_id, Party.creator_id == user.id,
        Party.status.in_([PartyStatus.waiting, PartyStatus.active]),
    ).first()
    if not party:
        raise HTTPException(404, "Party not found or already completed")

    party.status = PartyStatus.completed
    party.completed_at = datetime.utcnow()

    # Count joined members for group bonus
    joined = [m for m in party.members if m.status == "joined"]
    group_mult = GROUP_XP_MULTIPLIER if len(joined) >= 1 else 1.0
    xp = int(party.xp_reward * group_mult)

    # Award XP to creator
    user.xp = (user.xp or 0) + xp
    from .gamification import level_from_xp
    user.level = level_from_xp(user.xp)

    # Auto-create next occurrence for recurring parties
    if party.is_recurring and party.recurrence:
        recurrence_days = {"weekly": 7, "biweekly": 14, "monthly": 30}
        days = recurrence_days.get(party.recurrence.value, 7)
        next_date = (party.scheduled_at or datetime.utcnow()) + timedelta(days=days)

        next_party = Party(
            creator_id=user.id,
            title=party.title,
            activity_type=party.activity_type,
            description=party.description,
            location=party.location,
            scheduled_at=next_date,
            xp_reward=party.xp_reward,
            is_recurring=True,
            recurrence=party.recurrence,
        )
        db.add(next_party)
        db.commit()
        db.refresh(next_party)

        # Re-invite the same contacts
        for m in party.members:
            new_member = PartyMember(
                party_id=next_party.id, contact_id=m.contact_id, status="invited"
            )
            db.add(new_member)

    db.commit()
    return {
        "status": "completed",
        "party_id": party_id,
        "xp_earned": xp,
        "group_bonus": group_mult > 1.0,
        "members_joined": len(joined),
    }


@app.post("/parties/{party_id}/join/{contact_id}")
def join_party(
    party_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    party = db.query(Party).filter(
        Party.id == party_id, Party.creator_id == user.id,
    ).first()
    if not party:
        raise HTTPException(404, "Party not found")

    member = db.query(PartyMember).filter(
        PartyMember.party_id == party_id,
        PartyMember.contact_id == contact_id,
    ).first()
    if not member:
        # Add new member
        contact = db.query(Contact).filter(
            Contact.id == contact_id, Contact.user_id == user.id
        ).first()
        if not contact:
            raise HTTPException(404, "Contact not found")
        member = PartyMember(party_id=party_id, contact_id=contact_id)
        db.add(member)

    member.status = "joined"
    member.joined_at = datetime.utcnow()
    db.commit()
    return {"status": "joined", "contact_id": contact_id}


@app.post("/parties/{party_id}/cancel")
def cancel_party(
    party_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    party = db.query(Party).filter(
        Party.id == party_id, Party.creator_id == user.id,
        Party.status.in_([PartyStatus.waiting, PartyStatus.active]),
    ).first()
    if not party:
        raise HTTPException(404, "Party not found")
    party.status = PartyStatus.cancelled
    db.commit()
    return {"status": "cancelled", "party_id": party_id}


def _party_to_out(party: Party, db: Session) -> PartyOut:
    members = []
    for m in party.members:
        contact = db.query(Contact).filter(Contact.id == m.contact_id).first()
        members.append(PartyMemberOut(
            id=m.id, contact_id=m.contact_id,
            contact_name=contact.name if contact else "Unknown",
            status=m.status, joined_at=m.joined_at,
        ))
    return PartyOut(
        id=party.id, creator_id=party.creator_id, title=party.title,
        activity_type=party.activity_type, description=party.description,
        location=party.location, scheduled_at=party.scheduled_at,
        max_members=party.max_members, xp_reward=party.xp_reward,
        status=party.status, completed_at=party.completed_at,
        created_at=party.created_at, members=members,
    )


# ══════════════════════════════════════════════
# CHALLENGES (protected)
# ══════════════════════════════════════════════

@app.post("/challenges", response_model=ChallengeOut)
@limiter.limit("30/minute")
def create_challenge(
    request: Request,
    data: ChallengeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = db.query(Contact).filter(
        Contact.id == data.contact_id, Contact.user_id == user.id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    xp = ACTIVITY_XP.get(data.activity_type.value, 40)

    challenge = Challenge(
        challenger_id=user.id,
        contact_id=data.contact_id,
        title=data.title,
        description=data.description,
        activity_type=data.activity_type,
        xp_reward=xp,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    return ChallengeOut(
        id=challenge.id, challenger_id=challenge.challenger_id,
        contact_id=challenge.contact_id, contact_name=contact.name,
        title=challenge.title, description=challenge.description,
        activity_type=challenge.activity_type, xp_reward=challenge.xp_reward,
        status=challenge.status, expires_at=challenge.expires_at,
        completed_at=challenge.completed_at, created_at=challenge.created_at,
    )


@app.get("/challenges", response_model=list[ChallengeOut])
def list_challenges(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenges = (
        db.query(Challenge)
        .filter(Challenge.challenger_id == user.id)
        .order_by(Challenge.created_at.desc())
        .limit(20)
        .all()
    )
    result = []
    for c in challenges:
        contact = db.query(Contact).filter(Contact.id == c.contact_id).first()
        result.append(ChallengeOut(
            id=c.id, challenger_id=c.challenger_id,
            contact_id=c.contact_id, contact_name=contact.name if contact else "Unknown",
            title=c.title, description=c.description,
            activity_type=c.activity_type, xp_reward=c.xp_reward,
            status=c.status, expires_at=c.expires_at,
            completed_at=c.completed_at, created_at=c.created_at,
        ))
    return result


@app.post("/challenges/{challenge_id}/accept")
def accept_challenge(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge = db.query(Challenge).filter(
        Challenge.id == challenge_id, Challenge.challenger_id == user.id,
        Challenge.status == ChallengeStatus.pending,
    ).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found")
    challenge.status = ChallengeStatus.accepted
    db.commit()
    return {"status": "accepted", "challenge_id": challenge_id}


@app.post("/challenges/{challenge_id}/complete")
def complete_challenge(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge = db.query(Challenge).filter(
        Challenge.id == challenge_id, Challenge.challenger_id == user.id,
        Challenge.status.in_([ChallengeStatus.pending, ChallengeStatus.accepted]),
    ).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found or already completed")

    challenge.status = ChallengeStatus.completed
    challenge.completed_at = datetime.utcnow()

    xp = challenge.xp_reward
    user.xp = (user.xp or 0) + xp
    from .gamification import level_from_xp
    user.level = level_from_xp(user.xp)

    db.commit()
    return {"status": "completed", "challenge_id": challenge_id, "xp_earned": xp}


@app.post("/challenges/{challenge_id}/decline")
def decline_challenge(
    challenge_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    challenge = db.query(Challenge).filter(
        Challenge.id == challenge_id, Challenge.challenger_id == user.id,
        Challenge.status == ChallengeStatus.pending,
    ).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found")
    challenge.status = ChallengeStatus.declined
    db.commit()
    return {"status": "declined", "challenge_id": challenge_id}


# ══════════════════════════════════════════════
# SOCIAL FEED (protected)
# ══════════════════════════════════════════════

INTERACTION_ICONS = {
    "call": "\U0001F4DE", "video_call": "\U0001F4F9", "text": "\U0001F4AC",
    "in_person": "\U0001F91D", "social_media": "\U0001F4F1", "email": "\u2709\uFE0F",
}

FEED_ACTIVITY_ICONS = {
    "run": "\U0001F3C3", "gym": "\U0001F4AA", "hike": "\u26F0\uFE0F",
    "concert": "\U0001F3B5", "dinner": "\U0001F37D\uFE0F", "drinks": "\U0001F37B",
    "gaming": "\U0001F3AE", "movie": "\U0001F3AC", "sports": "\u26BD",
    "study": "\U0001F4DA", "custom": "\u2B50",
}


@app.get("/feed", response_model=list[FeedItemOut])
def get_feed(
    limit: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from .models import UserAchievement
    feed = []

    # 1. Recent interactions
    interactions = (
        db.query(Interaction, Contact)
        .join(Contact, Interaction.contact_id == Contact.id)
        .filter(Interaction.user_id == user.id)
        .order_by(Interaction.timestamp.desc())
        .limit(limit)
        .all()
    )
    for ix, contact in interactions:
        itype = ix.interaction_type.value
        feed.append(FeedItemOut(
            event_type="interaction",
            title=f"{itype.replace('_', ' ').title()} with {contact.name}",
            description=ix.notes or f"{ix.duration_minutes} min {itype.replace('_', ' ')}",
            icon=INTERACTION_ICONS.get(itype, "\U0001F4AC"),
            contact_name=contact.name,
            timestamp=ix.timestamp,
        ))

    # 2. Completed parties
    parties = (
        db.query(Party)
        .filter(Party.creator_id == user.id, Party.status == PartyStatus.completed)
        .order_by(Party.completed_at.desc())
        .limit(limit)
        .all()
    )
    for p in parties:
        member_count = len(p.members)
        feed.append(FeedItemOut(
            event_type="party_completed",
            title=f"Completed: {p.title}",
            description=f"{p.activity_type.value.title()} with {member_count} friend{'s' if member_count != 1 else ''}",
            icon=FEED_ACTIVITY_ICONS.get(p.activity_type.value, "\U0001F389"),
            xp=p.xp_reward,
            timestamp=p.completed_at or p.created_at,
        ))

    # 3. Completed challenges
    challenges = (
        db.query(Challenge, Contact)
        .join(Contact, Challenge.contact_id == Contact.id)
        .filter(Challenge.challenger_id == user.id, Challenge.status == ChallengeStatus.completed)
        .order_by(Challenge.completed_at.desc())
        .limit(limit)
        .all()
    )
    for c, contact in challenges:
        feed.append(FeedItemOut(
            event_type="challenge_completed",
            title=f"Challenge completed: {c.title}",
            description=f"vs {contact.name}",
            icon="\U0001F3C6",
            xp=c.xp_reward,
            contact_name=contact.name,
            timestamp=c.completed_at or c.created_at,
        ))

    # 4. Achievements
    achievements = (
        db.query(UserAchievement)
        .filter(UserAchievement.user_id == user.id)
        .order_by(UserAchievement.earned_at.desc())
        .limit(limit)
        .all()
    )
    achiev_map = {key: (name, icon) for key, name, _, icon, _ in ACHIEVEMENT_DEFS}
    for ua in achievements:
        name, icon = achiev_map.get(ua.achievement_key, (ua.achievement_key, "\U0001F3C5"))
        feed.append(FeedItemOut(
            event_type="achievement",
            title=f"Achievement unlocked: {name}",
            description="",
            icon=icon,
            timestamp=ua.earned_at,
        ))

    # Sort all by timestamp, most recent first
    feed.sort(key=lambda f: f.timestamp, reverse=True)
    return feed[:limit]


# ══════════════════════════════════════════════
# LEADERBOARD (protected)
# ══════════════════════════════════════════════

@app.get("/leaderboard", response_model=LeaderboardOut)
def get_leaderboard(
    days: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contacts = db.query(Contact).filter(Contact.user_id == user.id).all()
    since = datetime.utcnow() - timedelta(days=days)

    # Most interactions in period
    interaction_counts = {}
    for c in contacts:
        count = (
            db.query(func.count(Interaction.id))
            .filter(Interaction.contact_id == c.id, Interaction.timestamp >= since)
            .scalar() or 0
        )
        interaction_counts[c.id] = count

    most_interactions = sorted(contacts, key=lambda c: interaction_counts.get(c.id, 0), reverse=True)
    most_interactions_out = [
        LeaderboardEntryOut(
            contact_id=c.id, contact_name=c.name,
            relationship_type=c.relationship_type.value,
            value=interaction_counts.get(c.id, 0), rank=i + 1,
        )
        for i, c in enumerate(most_interactions[:10])
    ]

    # Highest relationship XP
    by_xp = sorted(contacts, key=lambda c: c.relationship_xp or 0, reverse=True)
    highest_xp_out = [
        LeaderboardEntryOut(
            contact_id=c.id, contact_name=c.name,
            relationship_type=c.relationship_type.value,
            value=c.relationship_xp or 0, rank=i + 1,
        )
        for i, c in enumerate(by_xp[:10])
    ]

    # Longest active streak (days since last interaction, inverted — most recent = best)
    streak_data = []
    for c in contacts:
        last_ix = (
            db.query(Interaction)
            .filter(Interaction.contact_id == c.id)
            .order_by(Interaction.timestamp.desc())
            .first()
        )
        if last_ix:
            days_since = (datetime.utcnow() - last_ix.timestamp).total_seconds() / 86400
            streak_data.append((c, max(0, days - days_since)))
        else:
            streak_data.append((c, 0))

    streak_data.sort(key=lambda x: x[1], reverse=True)
    longest_streak_out = [
        LeaderboardEntryOut(
            contact_id=c.id, contact_name=c.name,
            relationship_type=c.relationship_type.value,
            value=round(score, 1), rank=i + 1,
        )
        for i, (c, score) in enumerate(streak_data[:10])
    ]

    return LeaderboardOut(
        most_interactions=most_interactions_out,
        highest_relationship_xp=highest_xp_out,
        longest_streak=longest_streak_out,
    )


# ══════════════════════════════════════════════
# LOCATION / NEARBY (protected)
# ══════════════════════════════════════════════

@app.post("/location", response_model=dict)
def update_user_location(
    data: LocationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if data.city:
        user.city = data.city
    if data.latitude is not None:
        user.latitude = data.latitude
    if data.longitude is not None:
        user.longitude = data.longitude
    db.commit()
    return {"status": "updated", "city": user.city}


@app.get("/nearby", response_model=list[NearbyContactOut])
def get_nearby_contacts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user.city:
        return []

    # Find contacts in the same city
    contacts = (
        db.query(Contact)
        .filter(Contact.user_id == user.id, Contact.city == user.city, Contact.city != "")
        .all()
    )

    result = []
    now = datetime.utcnow()
    for c in contacts:
        last_ix = (
            db.query(Interaction)
            .filter(Interaction.contact_id == c.id)
            .order_by(Interaction.timestamp.desc())
            .first()
        )
        days_since = (now - last_ix.timestamp).total_seconds() / 86400 if last_ix else 999

        freq_days = FREQUENCY_DAYS.get(c.target_frequency, 14)
        if days_since > freq_days * 0.5:
            suggestion = f"You're both in {user.city} — grab coffee with {c.name}!"
        else:
            suggestion = f"{c.name} is nearby — catch up soon?"

        result.append(NearbyContactOut(
            contact_id=c.id,
            contact_name=c.name,
            city=c.city,
            relationship_type=c.relationship_type.value,
            days_since_contact=round(days_since, 1),
            suggestion=suggestion,
        ))

    result.sort(key=lambda x: x.days_since_contact, reverse=True)
    return result


# ══════════════════════════════════════════════
# STRAVA INTEGRATION (protected)
# ══════════════════════════════════════════════

STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID", "")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET", "")
STRAVA_REDIRECT_URI = os.environ.get("STRAVA_REDIRECT_URI", "")


@app.get("/strava/status", response_model=StravaStatusOut)
def strava_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conn = db.query(StravaConnection).filter(StravaConnection.user_id == user.id).first()
    if conn:
        return StravaStatusOut(
            connected=True, athlete_id=conn.strava_athlete_id,
            connected_at=conn.connected_at,
        )
    return StravaStatusOut(connected=False)


@app.get("/strava/connect")
def strava_connect(user: User = Depends(get_current_user)):
    if not STRAVA_CLIENT_ID:
        raise HTTPException(503, "Strava integration not configured")
    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={STRAVA_CLIENT_ID}"
        f"&redirect_uri={STRAVA_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=activity:read_all"
        f"&state={user.id}"
    )
    return {"auth_url": auth_url}


@app.get("/strava/callback")
def strava_callback(
    code: str,
    state: str,
    db: Session = Depends(get_db),
):
    import httpx

    if not STRAVA_CLIENT_ID or not STRAVA_CLIENT_SECRET:
        raise HTTPException(503, "Strava integration not configured")

    # Exchange code for token
    resp = httpx.post("https://www.strava.com/oauth/token", data={
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    })
    if resp.status_code != 200:
        raise HTTPException(400, "Strava auth failed")

    data = resp.json()
    user_id = int(state)

    # Upsert connection
    existing = db.query(StravaConnection).filter(StravaConnection.user_id == user_id).first()
    if existing:
        existing.access_token = data["access_token"]
        existing.refresh_token = data["refresh_token"]
        existing.expires_at = data["expires_at"]
        existing.strava_athlete_id = data["athlete"]["id"]
    else:
        conn = StravaConnection(
            user_id=user_id,
            strava_athlete_id=data["athlete"]["id"],
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
        )
        db.add(conn)
    db.commit()
    return {"status": "connected", "athlete_id": data["athlete"]["id"]}


@app.post("/strava/webhook")
async def strava_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive Strava activity webhook — auto-verify challenges/parties."""
    body = await request.json()

    if body.get("aspect_type") != "create" or body.get("object_type") != "activity":
        return {"status": "ignored"}

    athlete_id = body.get("owner_id")
    conn = db.query(StravaConnection).filter(
        StravaConnection.strava_athlete_id == athlete_id
    ).first()
    if not conn:
        return {"status": "unknown_athlete"}

    # Map Strava activity type to our ActivityType
    strava_type = body.get("activity_type", "").lower()
    type_map = {
        "run": "run", "ride": "run", "hike": "hike", "walk": "hike",
        "workout": "gym", "weighttraining": "gym", "swim": "sports",
    }
    our_type = type_map.get(strava_type)
    if not our_type:
        return {"status": "unmapped_type", "strava_type": strava_type}

    # Auto-complete matching pending challenges
    pending = (
        db.query(Challenge)
        .filter(
            Challenge.challenger_id == conn.user_id,
            Challenge.activity_type == our_type,
            Challenge.status.in_([ChallengeStatus.pending, ChallengeStatus.accepted]),
        )
        .all()
    )
    user = db.query(User).filter(User.id == conn.user_id).first()
    from .gamification import level_from_xp

    completed_ids = []
    for c in pending:
        c.status = ChallengeStatus.completed
        c.completed_at = datetime.utcnow()
        if user:
            user.xp = (user.xp or 0) + c.xp_reward
            user.level = level_from_xp(user.xp)
        completed_ids.append(c.id)

    db.commit()
    return {
        "status": "processed",
        "challenges_completed": completed_ids,
        "activity_type": our_type,
    }


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

    # Gamification data
    from .models import UserAchievement
    generate_quests(user, db)
    active_quests = (
        db.query(Quest)
        .filter(Quest.user_id == user.id, Quest.status == QuestStatus.active)
        .all()
    )
    earned_map = {
        ua.achievement_key: ua.earned_at
        for ua in db.query(UserAchievement).filter(UserAchievement.user_id == user.id).all()
    }
    all_achiev = [
        AchievementDef(
            key=key, name=name, description=desc, icon=icon, xp_bonus=xp,
            earned=key in earned_map, earned_at=earned_map.get(key),
        )
        for key, name, desc, icon, xp in ACHIEVEMENT_DEFS
    ]
    recent_achiev = [a for a in all_achiev if a.earned][-5:]

    # Active parties
    active_party_models = (
        db.query(Party)
        .filter(Party.creator_id == user.id, Party.status.in_([PartyStatus.waiting, PartyStatus.active]))
        .order_by(Party.created_at.desc())
        .limit(5)
        .all()
    )
    active_parties_out = [_party_to_out(p, db) for p in active_party_models]

    # Active challenges
    active_challenge_models = (
        db.query(Challenge)
        .filter(
            Challenge.challenger_id == user.id,
            Challenge.status.in_([ChallengeStatus.pending, ChallengeStatus.accepted]),
        )
        .order_by(Challenge.created_at.desc())
        .limit(5)
        .all()
    )
    active_challenges_out = []
    for c in active_challenge_models:
        ct = db.query(Contact).filter(Contact.id == c.contact_id).first()
        active_challenges_out.append(ChallengeOut(
            id=c.id, challenger_id=c.challenger_id,
            contact_id=c.contact_id, contact_name=ct.name if ct else "Unknown",
            title=c.title, description=c.description,
            activity_type=c.activity_type, xp_reward=c.xp_reward,
            status=c.status, expires_at=c.expires_at,
            completed_at=c.completed_at, created_at=c.created_at,
        ))

    gamification = GamificationDashboardOut(
        level_progress=LevelProgressOut(**level_progress(user.xp or 0)),
        streak_days=user.streak_days or 0,
        active_quests=[QuestOut.model_validate(q) for q in active_quests],
        recent_achievements=recent_achiev,
        all_achievements=all_achiev,
        active_parties=active_parties_out,
        active_challenges=active_challenges_out,
    )

    return DashboardOut(
        total_contacts=len(contacts_list),
        inner_circle_count=len(inner_circle),
        avg_health=round(avg_health, 1),
        interactions_this_week=interactions_week,
        health_reports=reports,
        top_nudges=top_nudges,
        ai_summary=ai_summary,
        gamification=gamification,
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
