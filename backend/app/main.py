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
import csv
import io
import re
import time
import random
import logging
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, date
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

log = logging.getLogger("orbit.api")

from .database import Base, engine, get_db
from .models import (
    User, Contact, Interaction, Weights, Nudge, LifeEvent, Quest,
    Party, PartyMember, Challenge, StravaConnection, Gate, BossRaid, PushToken,
    QuestChain, QuestChainStatus, UserSkill, Circle, CircleMember, CircleQuest,
    InteractionType, NudgeStatus, QuestStatus, PartyStatus, ChallengeStatus, Recurrence,
    HunterRank,
    INTERACTION_DEPTH, FREQUENCY_DAYS,
)
from .schemas import (
    UserCreate, UserOut,
    ContactCreate, ContactUpdate, ContactOut,
    InteractionCreate, InteractionOut,
    HealthReportOut, WeightsOut,
    LifeEventCreate, LifeEventOut,
    NudgeOut, DashboardOut,
    SignupRequest, LoginRequest, PasswordChangeRequest, TokenResponse,
    ForgotPasswordRequest, ResetPasswordRequest, VerifyEmailRequest, PushTokenRegister,
    ConversationStartersOut, AISummaryOut,
    QuestOut, AchievementDef, XPAwardOut, LevelProgressOut,
    GamificationDashboardOut,
    PartyCreate, PartyOut, PartyMemberOut,
    ChallengeCreate, ChallengeOut,
    FeedItemOut, LeaderboardOut, LeaderboardEntryOut,
    NearbyContactOut, LocationUpdate, StravaStatusOut,
    GateOut, GateCreate, StatAllocation, ShadowExtractOut,
    BossRaidCreate, BossRaidOut,
    AppleLoginRequest, GoogleLoginRequest,
    QuestChainOut, QuestChainStepOut,
    SkillTreeOut, ChooseClassRequest, UnlockSkillRequest,
    CircleCreate, CircleOut, CircleMemberOut, CircleQuestOut,
    StatBonusesOut,
)
from .decay import compute_health, compute_health_batch, update_weights_after_interaction
from .auth import (
    hash_password, verify_password, create_access_token, get_current_user,
    decode_purpose_token, send_verification_email, send_reset_email,
)
from .ai import generate_conversation_starters, generate_relationship_summary
from .gamification import (
    award_interaction_xp, generate_quests, complete_quest,
    level_progress, ACHIEVEMENT_DEFS,
    get_stat_bonuses, recover_hp, HP_POTION_COST, HP_POTION_HEAL, HP_MAX,
    get_user_chains, start_quest_chain, check_chain_step,
    BOSS_TEMPLATES, calculate_boss_damage,
    choose_social_class, unlock_skill, get_skill_tree, SOCIAL_CLASSES,
    create_circle_quest, circle_level_from_xp, CIRCLE_XP_BONUS,
    QUEST_CHAIN_DEFS, check_achievements,
)


# ── Rate limiter ──
def _get_real_ip(request: Request) -> str:
    """Extract real client IP from X-Forwarded-For (behind reverse proxy)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

limiter = Limiter(key_func=_get_real_ip)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Orbit API",
    description="Relationship Intelligence Backend",
    version="0.5.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──
_origins_env = os.environ.get("ALLOWED_ORIGINS", "")
if _origins_env:
    ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]
elif os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("PORT"):
    # Production: only allow our own domain + Capacitor origins
    ALLOWED_ORIGINS = [
        "https://orbit-app-production-fd37.up.railway.app",
        "capacitor://localhost",   # iOS Capacitor
        "http://localhost",        # Android Capacitor
    ]
else:
    ALLOWED_ORIGINS = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True if ALLOWED_ORIGINS != ["*"] else False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Sentry error tracking (optional) ──
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if _SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            traces_sample_rate=0.1,
            environment=os.environ.get("RAILWAY_ENVIRONMENT", "development"),
        )
        log.info("Sentry error tracking enabled")
    except ImportError:
        log.warning("SENTRY_DSN set but sentry-sdk not installed")


# ── Global exception handler ──
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions — log the full traceback, return a safe response."""
    log.error("Unhandled exception on %s %s: %s\n%s",
              request.method, request.url.path, exc, traceback.format_exc())
    if _SENTRY_DSN:
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)
        except Exception:
            pass
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ── Request logging ──
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000)
    if request.url.path not in ("/health", "/favicon.ico"):
        log.info("%s %s → %s (%dms)", request.method, request.url.path, response.status_code, duration_ms)
    return response


# ── Request body size limit (1MB) ──
MAX_BODY_SIZE = int(os.environ.get("MAX_BODY_SIZE", str(1024 * 1024)))


@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_SIZE:
        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    return await call_next(request)


# ── Security headers middleware ──
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://appleid.cdn-apple.com https://accounts.google.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' https://appleid.apple.com https://accounts.google.com https://oauth2.googleapis.com; "
        "frame-src https://appleid.apple.com https://accounts.google.com; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    return response


# ── In-memory rate limiter (60 req/min per IP) ──
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_last_cleanup = time.time()
RATE_LIMIT_MAX_REQUESTS = 60
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_IPS = 10000  # Prevent unbounded memory growth


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    global _rate_limit_last_cleanup
    # Use X-Forwarded-For behind reverse proxy (Railway, etc.)
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    # Periodic cleanup: evict stale IPs every 5 minutes
    if now - _rate_limit_last_cleanup > 300:
        stale = [ip for ip, ts in _rate_limit_store.items() if not ts or ts[-1] < window_start]
        for ip in stale:
            del _rate_limit_store[ip]
        _rate_limit_last_cleanup = now

    # Cap total tracked IPs to prevent memory exhaustion
    if len(_rate_limit_store) > RATE_LIMIT_MAX_IPS and client_ip not in _rate_limit_store:
        pass  # Don't track new IPs when at capacity (fail open)
    else:
        timestamps = _rate_limit_store[client_ip]
        _rate_limit_store[client_ip] = [t for t in timestamps if t > window_start]

        if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX_REQUESTS:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Max 60 requests per minute."},
            )
        _rate_limit_store[client_ip].append(now)

    response = await call_next(request)
    return response


# ── Input sanitization ──
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_SCRIPT_RE = re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL)


def sanitize(text: str) -> str:
    """Strip HTML tags and script content from user input."""
    if not text:
        return text
    text = _SCRIPT_RE.sub('', text)
    text = _HTML_TAG_RE.sub('', text)
    return text.strip()


# ══════════════════════════════════════════════
# AUTH ENDPOINTS (public)
# ══════════════════════════════════════════════

@app.post("/auth/signup", response_model=TokenResponse)
@limiter.limit("5/minute")
async def signup(request: Request, data: SignupRequest, db: Session = Depends(get_db)):
    data.email = data.email.strip().lower()
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(400, "Email already registered")

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        name=sanitize(data.name),
        timezone=data.timezone,
        email_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Send verification email (non-blocking — don't fail signup if email fails)
    try:
        await send_verification_email(user.id, user.email, user.name)
    except Exception:
        pass  # Email failure shouldn't block signup

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@app.post("/auth/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    data.email = data.email.strip().lower()
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@app.post("/auth/apple", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login_apple(request: Request, data: AppleLoginRequest, db: Session = Depends(get_db)):
    """Sign in with Apple. Creates account on first use."""
    from .social_auth import verify_apple_token

    try:
        apple_user = await verify_apple_token(data.id_token)
    except ValueError as e:
        raise HTTPException(401, str(e))

    provider_id = f"apple_{apple_user['sub']}"
    apple_email = apple_user["email"].strip().lower()

    # Check if user already exists with this Apple ID
    user = db.query(User).filter(User.auth_provider_id == provider_id).first()
    if not user:
        # Check if email already exists (link accounts)
        user = db.query(User).filter(User.email == apple_email).first()
        if user:
            # Link existing email account to Apple
            user.auth_provider = "apple"
            user.auth_provider_id = provider_id
            user.email_verified = True
            db.commit()
        else:
            # Create new account — wrap in try/except for race condition
            name = data.name or apple_email.split("@")[0]
            user = User(
                email=apple_email,
                name=name,
                timezone=data.timezone,
                auth_provider="apple",
                auth_provider_id=provider_id,
                email_verified=True,
            )
            db.add(user)
            try:
                db.commit()
            except Exception:
                db.rollback()
                # Race condition: another request created the user — fetch it
                user = db.query(User).filter(User.auth_provider_id == provider_id).first()
                if not user:
                    user = db.query(User).filter(User.email == apple_email).first()
                if not user:
                    raise HTTPException(500, "Account creation failed — please try again")
            else:
                db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@app.post("/auth/google", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login_google(request: Request, data: GoogleLoginRequest, db: Session = Depends(get_db)):
    """Sign in with Google. Creates account on first use."""
    from .social_auth import verify_google_token

    try:
        google_user = await verify_google_token(data.id_token)
    except ValueError as e:
        raise HTTPException(401, str(e))

    provider_id = f"google_{google_user['sub']}"
    google_email = google_user["email"].strip().lower()

    # Check if user already exists with this Google ID
    user = db.query(User).filter(User.auth_provider_id == provider_id).first()
    if not user:
        # Check if email already exists (link accounts)
        user = db.query(User).filter(User.email == google_email).first()
        if user:
            user.auth_provider = "google"
            user.auth_provider_id = provider_id
            user.email_verified = True
            db.commit()
        else:
            user = User(
                email=google_email,
                name=google_user.get("name") or google_email.split("@")[0],
                timezone=data.timezone,
                auth_provider="google",
                auth_provider_id=provider_id,
                email_verified=True,
            )
            db.add(user)
            try:
                db.commit()
            except Exception:
                db.rollback()
                user = db.query(User).filter(User.auth_provider_id == provider_id).first()
                if not user:
                    user = db.query(User).filter(User.email == google_email).first()
                if not user:
                    raise HTTPException(500, "Account creation failed — please try again")
            else:
                db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@app.get("/auth/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)):
    return user


@app.patch("/auth/password")
def change_password(
    data: PasswordChangeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.auth_provider != "email":
        raise HTTPException(400, f"Password changes not available for {user.auth_provider} accounts")
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"status": "password_changed"}


@app.delete("/auth/account")
@limiter.limit("3/hour")
def delete_account(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Delete all user data in dependency order
    from .models import (
        Weights, LifeEvent, Nudge, Quest, UserAchievement,
        Party, PartyMember, Challenge, BossRaid, StravaConnection,
    )

    contacts = db.query(Contact).filter(Contact.user_id == user.id).all()
    contact_ids = [c.id for c in contacts]

    if contact_ids:
        # Delete data referencing contacts first
        db.query(CircleMember).filter(CircleMember.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.query(PartyMember).filter(PartyMember.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.query(Challenge).filter(Challenge.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.query(Weights).filter(Weights.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.query(LifeEvent).filter(LifeEvent.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.query(Nudge).filter(Nudge.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.query(Quest).filter(Quest.contact_id.in_(contact_ids)).delete(synchronize_session=False)

    # Delete user-level data
    db.query(CircleQuest).filter(CircleQuest.user_id == user.id).delete()
    db.query(Circle).filter(Circle.user_id == user.id).delete()
    db.query(QuestChain).filter(QuestChain.user_id == user.id).delete()
    db.query(UserSkill).filter(UserSkill.user_id == user.id).delete()
    db.query(Interaction).filter(Interaction.user_id == user.id).delete()
    db.query(Contact).filter(Contact.user_id == user.id).delete()
    db.query(Quest).filter(Quest.user_id == user.id).delete()
    db.query(Nudge).filter(Nudge.user_id == user.id).delete()
    db.query(UserAchievement).filter(UserAchievement.user_id == user.id).delete()
    db.query(Party).filter(Party.creator_id == user.id).delete()
    db.query(Challenge).filter(Challenge.challenger_id == user.id).delete()
    db.query(Gate).filter(Gate.creator_id == user.id).delete()
    db.query(BossRaid).filter(BossRaid.creator_id == user.id).delete()
    db.query(StravaConnection).filter(StravaConnection.user_id == user.id).delete()
    db.query(PushToken).filter(PushToken.user_id == user.id).delete()

    db.delete(user)
    db.commit()
    return {"status": "account_deleted"}


# ── Email Verification & Password Reset ──

@app.post("/auth/verify-email")
async def verify_email(data: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify a user's email using the token from the verification email."""
    payload = decode_purpose_token(data.token, "verify")
    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.email_verified:
        return {"status": "already_verified"}
    user.email_verified = True
    db.commit()
    return {"status": "verified"}


@app.post("/auth/resend-verification")
@limiter.limit("3/minute")
async def resend_verification(request: Request, user: User = Depends(get_current_user)):
    """Resend the verification email for the current user."""
    if user.email_verified:
        return {"status": "already_verified"}
    await send_verification_email(user.id, user.email, user.name)
    return {"status": "sent"}


@app.post("/auth/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(request: Request, data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Send a password reset email. Always returns success to prevent email enumeration."""
    data.email = data.email.strip().lower()
    user = db.query(User).filter(User.email == data.email).first()
    if user:
        await send_reset_email(user.id, user.email, user.name)
    # Always return success to prevent email enumeration
    return {"status": "sent", "message": "If that email exists, a reset link has been sent."}


@app.post("/auth/reset-password")
@limiter.limit("5/minute")
async def reset_password(request: Request, data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset password using the token from the reset email."""
    payload = decode_purpose_token(data.token, "reset")
    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"status": "password_reset"}


# ── Push Notification Token Management ──

@app.post("/auth/push-token")
@limiter.limit("10/minute")
def register_push_token(
    request: Request,
    data: PushTokenRegister,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Register or update a device push notification token."""
    existing = db.query(PushToken).filter(PushToken.token == data.token).first()
    if existing:
        existing.user_id = user.id
        existing.platform = data.platform
        existing.active = True
        existing.updated_at = datetime.utcnow()
    else:
        db.add(PushToken(
            user_id=user.id,
            token=data.token,
            platform=data.platform,
        ))
    db.commit()
    return {"status": "registered"}


@app.delete("/auth/push-token")
def unregister_push_token(
    data: PushTokenRegister,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Deactivate a push token (e.g., on logout)."""
    token = db.query(PushToken).filter(
        PushToken.token == data.token,
        PushToken.user_id == user.id,
    ).first()
    if token:
        token.active = False
        db.commit()
    return {"status": "unregistered"}


@app.post("/notifications/send-nudges")
async def send_nudge_notifications(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Send push notifications for all pending nudges.
    Designed to be called by a cron job or scheduler.
    Protected by an API key in the Authorization header.
    """
    import os
    cron_key = os.environ.get("CRON_API_KEY", "")
    auth_header = request.headers.get("Authorization", "")

    # Allow either cron key or a valid user token (for manual testing)
    if cron_key and auth_header == f"Bearer {cron_key}":
        pass  # Authorized via cron key
    else:
        # Try user auth — only allow if user exists (for dev testing)
        try:
            get_current_user(auth_header.replace("Bearer ", ""), db)
        except Exception:
            raise HTTPException(401, "Unauthorized — set CRON_API_KEY env var")

    from .push import send_push_to_user

    # Find all pending nudges that haven't been pushed yet
    pending_nudges = (
        db.query(Nudge)
        .filter(Nudge.status == NudgeStatus.pending)
        .order_by(Nudge.priority.desc())
        .limit(100)
        .all()
    )

    sent_count = 0
    user_cache: dict = {}

    for nudge in pending_nudges:
        # Get user's contact name for the nudge
        contact = db.query(Contact).filter(Contact.id == nudge.contact_id).first()
        contact_name = contact.name if contact else "someone"

        title = "Orbit Nudge"
        body = nudge.message or f"Time to reach out to {contact_name}!"

        if nudge.suggestion:
            body += f" — {nudge.suggestion}"

        result = await send_push_to_user(
            db=db,
            user_id=nudge.user_id,
            title=title,
            body=body,
            data={"page": "contacts", "nudge_id": str(nudge.id)},
        )
        sent_count += result

    return {
        "status": "done",
        "nudges_processed": len(pending_nudges),
        "notifications_sent": sent_count,
    }


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
        name=sanitize(data.name),
        relationship_type=data.relationship_type,
        target_frequency=data.target_frequency,
        notes=sanitize(data.notes),
        city=sanitize(data.city),
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
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return (
        db.query(Contact)
        .filter(Contact.user_id == user.id)
        .order_by(Contact.name)
        .offset(skip)
        .limit(min(limit, 200))
        .all()
    )


@app.delete("/contacts/{contact_id}")
def delete_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.user_id == user.id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")
    db.delete(contact)
    db.commit()
    return {"status": "deleted", "contact_id": contact_id}


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

    _text_fields = {"name", "notes", "city"}
    for field, value in data.model_dump(exclude_unset=True).items():
        if field in _text_fields and isinstance(value, str):
            value = sanitize(value)
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
        notes=sanitize(data.notes),
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
@limiter.limit("30/minute")
def create_life_event(
    request: Request,
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
        description=sanitize(data.description),
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
        title=sanitize(data.title),
        activity_type=data.activity_type,
        description=sanitize(data.description),
        location=sanitize(data.location),
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
        status=party.status, is_recurring=party.is_recurring or False,
        recurrence=party.recurrence, completed_at=party.completed_at,
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
        title=sanitize(data.title),
        description=sanitize(data.description),
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
    rows = (
        db.query(Challenge, Contact)
        .join(Contact, Challenge.contact_id == Contact.id)
        .filter(Challenge.challenger_id == user.id)
        .order_by(Challenge.created_at.desc())
        .limit(20)
        .all()
    )
    return [
        ChallengeOut(
            id=c.id, challenger_id=c.challenger_id,
            contact_id=c.contact_id, contact_name=contact.name,
            title=c.title, description=c.description,
            activity_type=c.activity_type, xp_reward=c.xp_reward,
            status=c.status, expires_at=c.expires_at,
            completed_at=c.completed_at, created_at=c.created_at,
        )
        for c, contact in rows
    ]


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
    if not contacts:
        empty = LeaderboardOut(most_interactions=[], highest_relationship_xp=[], longest_streak=[])
        return empty

    since = datetime.utcnow() - timedelta(days=days)
    contact_ids = [c.id for c in contacts]
    contact_map = {c.id: c for c in contacts}

    # Most interactions — single aggregation query instead of N queries
    ix_counts = (
        db.query(Interaction.contact_id, func.count(Interaction.id))
        .filter(Interaction.contact_id.in_(contact_ids), Interaction.timestamp >= since)
        .group_by(Interaction.contact_id)
        .all()
    )
    interaction_counts = {cid: cnt for cid, cnt in ix_counts}

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

    # Longest active streak — single query for last interaction per contact
    last_interactions = (
        db.query(Interaction.contact_id, func.max(Interaction.timestamp).label("last_ts"))
        .filter(Interaction.contact_id.in_(contact_ids))
        .group_by(Interaction.contact_id)
        .all()
    )
    last_ts_map = {cid: ts for cid, ts in last_interactions}
    now = datetime.utcnow()

    streak_data = []
    for c in contacts:
        last_ts = last_ts_map.get(c.id)
        if last_ts:
            days_since = (now - last_ts).total_seconds() / 86400
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


_strava_state_store: dict[str, int] = {}  # state_token -> user_id (short-lived)


@app.get("/strava/connect")
def strava_connect(user: User = Depends(get_current_user)):
    if not STRAVA_CLIENT_ID:
        raise HTTPException(503, "Strava integration not configured")
    import secrets
    state_token = secrets.token_urlsafe(32)
    _strava_state_store[state_token] = user.id
    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={STRAVA_CLIENT_ID}"
        f"&redirect_uri={STRAVA_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=activity:read_all"
        f"&state={state_token}"
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

    # Validate CSRF state token
    user_id = _strava_state_store.pop(state, None)
    if user_id is None:
        raise HTTPException(400, "Invalid or expired OAuth state")

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
    from sqlalchemy.orm import joinedload
    contacts_list = (
        db.query(Contact)
        .options(joinedload(Contact.weights))
        .filter(Contact.user_id == user.id)
        .all()
    )
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    reports = compute_health_batch(contacts_list, db, now)

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

    # Active challenges — single join query
    active_challenge_rows = (
        db.query(Challenge, Contact)
        .join(Contact, Challenge.contact_id == Contact.id)
        .filter(
            Challenge.challenger_id == user.id,
            Challenge.status.in_([ChallengeStatus.pending, ChallengeStatus.accepted]),
        )
        .order_by(Challenge.created_at.desc())
        .limit(5)
        .all()
    )
    active_challenges_out = [
        ChallengeOut(
            id=c.id, challenger_id=c.challenger_id,
            contact_id=c.contact_id, contact_name=ct.name,
            title=c.title, description=c.description,
            activity_type=c.activity_type, xp_reward=c.xp_reward,
            status=c.status, expires_at=c.expires_at,
            completed_at=c.completed_at, created_at=c.created_at,
        )
        for c, ct in active_challenge_rows
    ]

    # Fetch active gates for this user
    active_gates = (
        db.query(Gate)
        .filter(Gate.creator_id == user.id, Gate.status.in_(["open", "active"]))
        .all()
    )

    # Fetch active boss raids for this user
    active_boss_raid_models = (
        db.query(BossRaid)
        .filter(BossRaid.creator_id == user.id, BossRaid.status == "active")
        .order_by(BossRaid.created_at.desc())
        .limit(5)
        .all()
    )

    gamification = GamificationDashboardOut(
        level_progress=LevelProgressOut(**level_progress(user.xp or 0)),
        streak_days=user.streak_days or 0,
        active_quests=[QuestOut.model_validate(q) for q in active_quests],
        recent_achievements=recent_achiev,
        all_achievements=all_achiev,
        active_parties=active_parties_out,
        active_challenges=active_challenges_out,
        hunter_rank=user.hunter_rank.value if user.hunter_rank else "E-Rank",
        hp=user.hp or 100,
        stat_points=user.stat_points or 0,
        stats={
            "charisma": user.stat_charisma or 1,
            "empathy": user.stat_empathy or 1,
            "consistency": user.stat_consistency or 1,
            "initiative": user.stat_initiative or 1,
            "wisdom": user.stat_wisdom or 1,
        },
        shadow_army_count=user.shadow_army_count or 0,
        daily_quest_streak=user.daily_quest_streak or 0,
        active_gates=[
            GateOut(
                id=g.id, creator_id=g.creator_id, title=g.title,
                description=g.description or "",
                gate_rank=g.gate_rank.value if g.gate_rank else "E-Rank",
                xp_reward=g.xp_reward or 100,
                time_limit_hours=g.time_limit_hours or 24,
                status=g.status or "open",
                objective_type=g.objective_type or "interactions",
                objective_target=g.objective_target or 3,
                objective_current=g.objective_current or 0,
                expires_at=g.expires_at, cleared_at=g.cleared_at,
                created_at=g.created_at,
            )
            for g in active_gates
        ],
        active_boss_raids=[BossRaidOut.model_validate(r) for r in active_boss_raid_models],
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
# SOLO LEVELING — Stat Allocation, Shadow Army, Gates
# ══════════════════════════════════════════════

RANK_LEVELS = {
    "E-Rank": 1, "D-Rank": 5, "C-Rank": 10, "B-Rank": 18,
    "A-Rank": 28, "S-Rank": 40, "SS-Rank": 55, "Monarch": 75,
}

GATE_XP_REWARDS = {
    "E-Rank": 50, "D-Rank": 100, "C-Rank": 200, "B-Rank": 350,
    "A-Rank": 500, "S-Rank": 750, "SS-Rank": 1000, "Monarch": 2000,
}

SHADOW_GRADE_THRESHOLDS = {
    0: "normal", 50: "elite", 150: "knight", 400: "general", 1000: "marshal",
}


def compute_rank_for_level(level: int) -> str:
    rank = "E-Rank"
    for r, min_lvl in RANK_LEVELS.items():
        if level >= min_lvl:
            rank = r
    return rank


def compute_shadow_grade(relationship_xp: int) -> str:
    grade = "normal"
    for threshold, g in sorted(SHADOW_GRADE_THRESHOLDS.items()):
        if relationship_xp >= threshold:
            grade = g
    return grade


@app.post("/stats/allocate")
def allocate_stats(
    allocation: StatAllocation,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Spend stat points on hunter stats (Charisma, Empathy, Consistency, Initiative, Wisdom)."""
    total_requested = (
        allocation.charisma + allocation.empathy + allocation.consistency
        + allocation.initiative + allocation.wisdom
    )
    if total_requested <= 0:
        raise HTTPException(400, "Must allocate at least 1 point")
    if total_requested > (user.stat_points or 0):
        raise HTTPException(400, f"Not enough stat points. Have {user.stat_points}, need {total_requested}")

    user.stat_charisma = (user.stat_charisma or 1) + allocation.charisma
    user.stat_empathy = (user.stat_empathy or 1) + allocation.empathy
    user.stat_consistency = (user.stat_consistency or 1) + allocation.consistency
    user.stat_initiative = (user.stat_initiative or 1) + allocation.initiative
    user.stat_wisdom = (user.stat_wisdom or 1) + allocation.wisdom
    user.stat_points -= total_requested
    db.commit()
    db.refresh(user)

    return {
        "stat_points_remaining": user.stat_points,
        "stats": {
            "charisma": user.stat_charisma,
            "empathy": user.stat_empathy,
            "consistency": user.stat_consistency,
            "initiative": user.stat_initiative,
            "wisdom": user.stat_wisdom,
        },
    }


@app.post("/contacts/{contact_id}/extract-shadow", response_model=ShadowExtractOut)
def extract_shadow(
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Extract a contact into your Shadow Army. Grade depends on relationship XP."""
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.user_id == user.id
    ).first()
    if not contact:
        raise HTTPException(404, "Contact not found")
    if contact.shadow_grade:
        return ShadowExtractOut(
            success=False, shadow_grade=contact.shadow_grade,
            contact_name=contact.name,
            message=f"{contact.name} is already a shadow ({contact.shadow_grade})",
        )

    grade = compute_shadow_grade(contact.relationship_xp or 0)
    contact.shadow_grade = grade
    contact.shadow_extracted_at = datetime.utcnow()
    user.shadow_army_count = (user.shadow_army_count or 0) + 1

    # Bonus XP for extraction
    bonus_xp = {"normal": 10, "elite": 25, "knight": 50, "general": 100, "marshal": 250}.get(grade, 10)
    user.xp = (user.xp or 0) + bonus_xp

    # Check for rank up
    new_rank = compute_rank_for_level(user.level or 1)
    rank_enum = HunterRank(new_rank)
    if user.hunter_rank != rank_enum:
        user.hunter_rank = rank_enum

    db.commit()
    db.refresh(contact)

    return ShadowExtractOut(
        success=True, shadow_grade=grade,
        contact_name=contact.name,
        message=f"ARISE! {contact.name} has been extracted as a {grade} shadow! +{bonus_xp} XP",
    )


@app.post("/gates", response_model=GateOut)
def create_gate(
    gate_data: GateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Open a new gate (social challenge/dungeon)."""
    rank_str = gate_data.gate_rank if gate_data.gate_rank in RANK_LEVELS else "E-Rank"
    xp_reward = GATE_XP_REWARDS.get(rank_str, 50)

    gate = Gate(
        creator_id=user.id,
        title=sanitize(gate_data.title),
        description=sanitize(gate_data.description),
        gate_rank=HunterRank(rank_str),
        xp_reward=xp_reward,
        time_limit_hours=gate_data.time_limit_hours,
        status="open",
        objective_type=gate_data.objective_type,
        objective_target=gate_data.objective_target,
        objective_current=0,
        expires_at=datetime.utcnow() + timedelta(hours=gate_data.time_limit_hours),
    )
    db.add(gate)
    db.commit()
    db.refresh(gate)

    return GateOut(
        id=gate.id, creator_id=gate.creator_id, title=gate.title,
        description=gate.description or "",
        gate_rank=gate.gate_rank.value if gate.gate_rank else rank_str,
        xp_reward=gate.xp_reward, time_limit_hours=gate.time_limit_hours,
        status=gate.status, objective_type=gate.objective_type,
        objective_target=gate.objective_target, objective_current=gate.objective_current,
        expires_at=gate.expires_at, cleared_at=gate.cleared_at,
        created_at=gate.created_at,
    )


@app.get("/gates", response_model=list[GateOut])
def list_gates(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all gates for the user."""
    gates = db.query(Gate).filter(Gate.creator_id == user.id).order_by(Gate.created_at.desc()).all()
    return [
        GateOut(
            id=g.id, creator_id=g.creator_id, title=g.title,
            description=g.description or "",
            gate_rank=g.gate_rank.value if g.gate_rank else "E-Rank",
            xp_reward=g.xp_reward or 100, time_limit_hours=g.time_limit_hours or 24,
            status=g.status or "open", objective_type=g.objective_type or "interactions",
            objective_target=g.objective_target or 3, objective_current=g.objective_current or 0,
            expires_at=g.expires_at, cleared_at=g.cleared_at, created_at=g.created_at,
        )
        for g in gates
    ]


@app.post("/gates/{gate_id}/progress")
def update_gate_progress(
    gate_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Increment gate progress. Auto-clears when objective is met."""
    gate = db.query(Gate).filter(Gate.id == gate_id, Gate.creator_id == user.id).first()
    if not gate:
        raise HTTPException(404, "Gate not found")
    if gate.status in ("cleared", "failed"):
        raise HTTPException(400, f"Gate already {gate.status}")

    # Check expiry
    if gate.expires_at and datetime.utcnow() > gate.expires_at:
        gate.status = "failed"
        db.commit()
        return {"status": "failed", "message": "Gate expired! The dungeon has collapsed."}

    gate.objective_current = (gate.objective_current or 0) + 1
    gate.status = "active"

    if gate.objective_current >= (gate.objective_target or 3):
        # Gate cleared!
        gate.status = "cleared"
        gate.cleared_at = datetime.utcnow()
        user.xp = (user.xp or 0) + (gate.xp_reward or 100)

        # Grant stat points on gate clear
        stat_points_earned = {"E-Rank": 1, "D-Rank": 2, "C-Rank": 3, "B-Rank": 4,
                              "A-Rank": 5, "S-Rank": 7, "SS-Rank": 10, "Monarch": 15}
        rank_str = gate.gate_rank.value if gate.gate_rank else "E-Rank"
        user.stat_points = (user.stat_points or 0) + stat_points_earned.get(rank_str, 1)

        # Check rank up
        new_rank = compute_rank_for_level(user.level or 1)
        rank_enum = HunterRank(new_rank)
        if user.hunter_rank != rank_enum:
            user.hunter_rank = rank_enum

        db.commit()
        return {
            "status": "cleared",
            "message": f"Gate cleared! +{gate.xp_reward} XP, +{stat_points_earned.get(rank_str, 1)} stat points!",
            "xp_earned": gate.xp_reward,
            "stat_points_earned": stat_points_earned.get(rank_str, 1),
        }

    db.commit()
    return {
        "status": "active",
        "objective_current": gate.objective_current,
        "objective_target": gate.objective_target,
        "message": f"Progress: {gate.objective_current}/{gate.objective_target}",
    }


@app.post("/rank/check")
def check_rank(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recalculate hunter rank based on current level."""
    new_rank = compute_rank_for_level(user.level or 1)
    old_rank = user.hunter_rank.value if user.hunter_rank else "E-Rank"
    rank_enum = HunterRank(new_rank)
    ranked_up = old_rank != new_rank
    user.hunter_rank = rank_enum
    db.commit()

    return {
        "hunter_rank": new_rank,
        "previous_rank": old_rank,
        "ranked_up": ranked_up,
        "level": user.level,
    }


# ══════════════════════════════════════════════
# TITLE SYSTEM (protected)
# ══════════════════════════════════════════════

TITLE_CHECKS = [
    # (title, check_function) — ordered from lowest to highest priority
    ("Rookie Hunter", lambda user, gates_cleared: True),
    ("Shadow Soldier", lambda user, gates_cleared: (user.shadow_army_count or 0) >= 3),
    ("Gate Keeper", lambda user, gates_cleared: gates_cleared >= 3),
    ("Shadow Commander", lambda user, gates_cleared: (user.shadow_army_count or 0) >= 10),
    ("Elite Hunter", lambda user, gates_cleared: (user.level or 1) >= 10),
    ("S-Rank Hunter", lambda user, gates_cleared: (user.hunter_rank and user.hunter_rank.value in ("S-Rank", "SS-Rank", "Monarch"))),
    ("Shadow Monarch", lambda user, gates_cleared: (
        user.hunter_rank and user.hunter_rank.value == "Monarch"
        and (user.shadow_army_count or 0) >= 20
    )),
]


@app.post("/titles/check")
def check_title(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check user stats and award the highest earned title."""
    gates_cleared = (
        db.query(func.count(Gate.id))
        .filter(Gate.creator_id == user.id, Gate.status == "cleared")
        .scalar() or 0
    )

    best_title = "Rookie Hunter"
    for title, check_fn in TITLE_CHECKS:
        if check_fn(user, gates_cleared):
            best_title = title

    old_title = user.title or "Rookie Hunter"
    user.title = best_title
    db.commit()

    return {
        "title": best_title,
        "previous_title": old_title,
        "changed": old_title != best_title,
    }


# ══════════════════════════════════════════════
# DAILY LOGIN / CHECK-IN (protected)
# ══════════════════════════════════════════════

@app.post("/daily/check-in")
def daily_check_in(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Daily check-in: grant XP, manage streak, penalize missed days."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    last_active = user.last_active_date

    # Already checked in today
    if last_active == today:
        return {
            "checked_in": False,
            "xp_earned": 0,
            "hp_change": 0,
            "streak": user.daily_quest_streak or 0,
            "message": "Already checked in today!",
        }

    xp_earned = 15
    hp_change = 0
    streak = user.daily_quest_streak or 0

    if last_active is not None and last_active == yesterday:
        # Consecutive day
        streak += 1
        bonus_xp = 5 * min(streak, 10)
        xp_earned += bonus_xp
        message = f"Check-in successful! {streak}-day streak! +{xp_earned} XP"
    elif last_active is not None and last_active < yesterday:
        # Missed day(s) — penalize
        hp_loss = 10
        user.hp = max(10, (user.hp or 100) - hp_loss)
        hp_change = -hp_loss
        streak = 0
        message = f"Check-in successful! Streak broken. HP -{hp_loss}. +{xp_earned} XP"
    else:
        # First ever check-in (last_active is None) or same logic
        streak = 1
        message = f"Welcome! First check-in. +{xp_earned} XP"

    # Grant XP and stat point
    user.xp = (user.xp or 0) + xp_earned
    user.stat_points = (user.stat_points or 0) + 1
    user.daily_quest_streak = streak
    user.last_active_date = today

    # Update level
    from .gamification import level_from_xp
    user.level = level_from_xp(user.xp)

    db.commit()

    return {
        "checked_in": True,
        "xp_earned": xp_earned,
        "hp_change": hp_change,
        "streak": streak,
        "message": message,
    }


# ══════════════════════════════════════════════
# STREAK FREEZE (protected)
# ══════════════════════════════════════════════

@app.post("/streak/freeze")
def buy_streak_freeze(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Buy a streak freeze for 100 XP."""
    if (user.xp or 0) < 100:
        raise HTTPException(400, f"Not enough XP. Have {user.xp or 0}, need 100.")

    user.xp = (user.xp or 0) - 100
    user.streak_freezes = (user.streak_freezes or 0) + 1

    from .gamification import level_from_xp
    user.level = level_from_xp(user.xp)

    db.commit()

    return {
        "freezes": user.streak_freezes,
        "xp_remaining": user.xp,
    }


@app.post("/streak/use-freeze")
def use_streak_freeze(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Use a streak freeze to prevent streak from breaking."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    last_active = user.last_active_date

    # Check if streak would break (missed yesterday and haven't checked in today)
    streak_would_break = (
        last_active is not None
        and last_active < yesterday
        and last_active != today
    )

    if not streak_would_break:
        return {
            "used": False,
            "freezes_remaining": user.streak_freezes or 0,
            "message": "Streak is not in danger. No freeze needed.",
        }

    if (user.streak_freezes or 0) <= 0:
        return {
            "used": False,
            "freezes_remaining": 0,
            "message": "No streak freezes available.",
        }

    # Use the freeze — maintain streak, update last_active to yesterday
    user.streak_freezes -= 1
    user.last_active_date = yesterday
    db.commit()

    return {
        "used": True,
        "freezes_remaining": user.streak_freezes,
        "message": "Streak freeze used! Your streak is safe.",
    }


# ══════════════════════════════════════════════
# BOSS RAIDS (protected)
# ══════════════════════════════════════════════

@app.post("/boss-raids", response_model=BossRaidOut)
def create_boss_raid(
    data: BossRaidCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new boss raid. Optionally use a boss_type template."""
    # If boss_type is provided, use template values
    boss_type = getattr(data, 'boss_type', None) or "shadow_beast"
    template = BOSS_TEMPLATES.get(boss_type, BOSS_TEMPLATES["shadow_beast"])

    hp = template["hp"] if boss_type != "shadow_beast" else data.boss_hp
    xp_reward = template["xp_reward"] if boss_type != "shadow_beast" else data.xp_reward
    sp_reward = template.get("stat_points", 3)

    raid = BossRaid(
        creator_id=user.id,
        title=sanitize(data.title) or template["name"],
        description=sanitize(data.description) or template["description"],
        boss_name=sanitize(data.boss_name) or template["name"],
        boss_hp=hp,
        boss_max_hp=hp,
        xp_reward=xp_reward,
        time_limit_days=data.time_limit_days,
        expires_at=datetime.utcnow() + timedelta(days=data.time_limit_days),
        boss_type=boss_type,
        total_phases=template.get("phases", 1),
        stat_points_reward=sp_reward,
    )
    db.add(raid)
    db.commit()
    db.refresh(raid)
    return raid


@app.get("/boss-raids", response_model=list[BossRaidOut])
def list_boss_raids(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List user's boss raids."""
    return (
        db.query(BossRaid)
        .filter(BossRaid.creator_id == user.id)
        .order_by(BossRaid.created_at.desc())
        .all()
    )


@app.post("/boss-raids/{raid_id}/attack")
def attack_boss_raid(
    raid_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Deal damage to a boss raid. Damage based on stats and boss type mechanics."""
    raid = db.query(BossRaid).filter(
        BossRaid.id == raid_id, BossRaid.creator_id == user.id
    ).first()
    if not raid:
        raise HTTPException(404, "Boss raid not found")
    if raid.status != "active":
        raise HTTPException(400, f"Boss raid is {raid.status}, cannot attack")

    # Check expiry
    if raid.expires_at and datetime.utcnow() > raid.expires_at:
        raid.status = "failed"
        db.commit()
        return {"status": "failed", "message": "Boss raid expired! The beast escaped."}

    bonuses = get_stat_bonuses(user, db)

    # Create a mock interaction for damage calculation (basic attack)
    mock_interaction = type('obj', (object,), {
        'interaction_type': InteractionType.text,
        'duration_minutes': 0,
    })()
    damage = calculate_boss_damage(user, mock_interaction, raid, bonuses, db)
    raid.boss_hp = max(0, raid.boss_hp - damage)

    result = {
        "damage_dealt": damage,
        "boss_hp": raid.boss_hp,
        "boss_max_hp": raid.boss_max_hp,
        "boss_type": raid.boss_type or "shadow_beast",
    }

    if raid.boss_hp <= 0:
        raid.status = "cleared"
        raid.cleared_at = datetime.utcnow()

        sp_reward = raid.stat_points_reward or 3
        user.xp = (user.xp or 0) + raid.xp_reward
        user.stat_points = (user.stat_points or 0) + sp_reward
        from .gamification import level_from_xp
        user.level = level_from_xp(user.xp)

        recover_hp(user, "boss_clear")

        result["status"] = "cleared"
        result["message"] = f"Boss defeated! +{raid.xp_reward} XP, +{sp_reward} stat points!"
        result["xp_earned"] = raid.xp_reward
        result["stat_points_earned"] = sp_reward
    else:
        result["status"] = "active"
        result["message"] = f"Hit for {damage} damage! Boss HP: {raid.boss_hp}/{raid.boss_max_hp}"

    db.commit()
    return result


@app.get("/boss-templates")
def list_boss_templates(user: User = Depends(get_current_user)):
    """List available boss types for creating raids."""
    return [
        {
            "key": key,
            "name": t["name"],
            "description": t["description"],
            "hp": t["hp"],
            "xp_reward": t["xp_reward"],
            "stat_points": t["stat_points"],
            "phases": t["phases"],
            "mechanic": t["mechanic"],
        }
        for key, t in BOSS_TEMPLATES.items()
    ]


# ══════════════════════════════════════════════
# STAT BONUSES (protected)
# ══════════════════════════════════════════════

@app.get("/stats/bonuses", response_model=StatBonusesOut)
def get_bonuses(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get all mechanical bonuses from stats and skills."""
    return StatBonusesOut(**get_stat_bonuses(user, db))


# ══════════════════════════════════════════════
# HP POTION (protected)
# ══════════════════════════════════════════════

@app.post("/hp/potion")
def use_hp_potion(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Use an HP potion. Costs XP, recovers HP."""
    if (user.xp or 0) < HP_POTION_COST:
        raise HTTPException(400, f"Need {HP_POTION_COST} XP for a potion, have {user.xp or 0}")
    if (user.hp or 0) >= HP_MAX:
        raise HTTPException(400, "HP already full")

    user.xp = (user.xp or 0) - HP_POTION_COST
    old_hp = user.hp or 0
    user.hp = min(HP_MAX, old_hp + HP_POTION_HEAL)
    db.commit()

    return {
        "hp": user.hp,
        "hp_recovered": user.hp - old_hp,
        "xp_cost": HP_POTION_COST,
        "xp_remaining": user.xp,
    }


# ══════════════════════════════════════════════
# QUEST CHAINS (protected)
# ══════════════════════════════════════════════

@app.get("/quest-chains")
def list_quest_chains(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get all quest chains with progress."""
    return get_user_chains(user, db)


@app.post("/quest-chains/{chain_key}/start")
def start_chain(
    chain_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start a quest chain."""
    result = start_quest_chain(user, chain_key, db)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/quest-chains/{chain_key}/check")
def check_chain(
    chain_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check and advance current chain step if condition met."""
    chain = db.query(QuestChain).filter(
        QuestChain.user_id == user.id,
        QuestChain.chain_key == chain_key,
        QuestChain.status == QuestChainStatus.active,
    ).first()
    if not chain:
        raise HTTPException(404, "No active chain found")

    advanced = check_chain_step(user, chain, db)
    if advanced:
        check_achievements(user, None, db)

    return {
        "advanced": advanced,
        "current_step": chain.current_step,
        "status": chain.status.value,
        "chain_key": chain_key,
    }


# ══════════════════════════════════════════════
# SKILL TREE (protected)
# ══════════════════════════════════════════════

@app.get("/skills/tree")
def skill_tree(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get full skill tree with class info and skill states."""
    return get_skill_tree(user, db)


@app.post("/skills/choose-class")
def choose_class(
    data: ChooseClassRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Choose or switch social class."""
    result = choose_social_class(user, data.class_key, db)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/skills/unlock")
def skill_unlock(
    data: UnlockSkillRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unlock or level up a skill using SP."""
    result = unlock_skill(user, data.skill_key, db)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ══════════════════════════════════════════════
# CIRCLES (protected)
# ══════════════════════════════════════════════

def _circle_to_out(circle: Circle, db) -> dict:
    members = []
    for m in circle.members:
        contact = db.query(Contact).filter(Contact.id == m.contact_id).first()
        members.append({
            "id": m.id,
            "contact_id": m.contact_id,
            "contact_name": contact.name if contact else "Unknown",
            "joined_at": m.joined_at,
        })
    active_quests = db.query(CircleQuest).filter(
        CircleQuest.circle_id == circle.id,
        CircleQuest.status == "active",
    ).all()
    return {
        "id": circle.id,
        "user_id": circle.user_id,
        "name": circle.name,
        "description": circle.description,
        "icon": circle.icon,
        "xp_pool": circle.xp_pool or 0,
        "level": circle.level or 1,
        "created_at": circle.created_at,
        "members": members,
        "active_quests": [q for q in active_quests],
    }


@app.post("/circles")
def create_circle(
    data: CircleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new circle (contact group)."""
    circle = Circle(
        user_id=user.id,
        name=sanitize(data.name),
        description=sanitize(data.description),
        icon=data.icon,
    )
    db.add(circle)
    db.commit()
    db.refresh(circle)

    # Add contacts
    for cid in data.contact_ids:
        contact = db.query(Contact).filter(Contact.id == cid, Contact.user_id == user.id).first()
        if contact:
            member = CircleMember(circle_id=circle.id, contact_id=cid)
            db.add(member)
    db.commit()
    db.refresh(circle)

    # Check achievement
    check_achievements(user, None, db)

    return _circle_to_out(circle, db)


@app.get("/circles")
def list_circles(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all user's circles."""
    circles = db.query(Circle).filter(Circle.user_id == user.id).all()
    return [_circle_to_out(c, db) for c in circles]


@app.get("/circles/{circle_id}")
def get_circle(
    circle_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get circle details."""
    circle = db.query(Circle).filter(Circle.id == circle_id, Circle.user_id == user.id).first()
    if not circle:
        raise HTTPException(404, "Circle not found")
    return _circle_to_out(circle, db)


@app.post("/circles/{circle_id}/members/{contact_id}")
def add_circle_member(
    circle_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add a contact to a circle."""
    circle = db.query(Circle).filter(Circle.id == circle_id, Circle.user_id == user.id).first()
    if not circle:
        raise HTTPException(404, "Circle not found")
    contact = db.query(Contact).filter(Contact.id == contact_id, Contact.user_id == user.id).first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    existing = db.query(CircleMember).filter(
        CircleMember.circle_id == circle_id,
        CircleMember.contact_id == contact_id,
    ).first()
    if existing:
        raise HTTPException(400, "Contact already in circle")

    member = CircleMember(circle_id=circle_id, contact_id=contact_id)
    db.add(member)
    db.commit()
    return {"status": "added", "contact_name": contact.name}


@app.delete("/circles/{circle_id}/members/{contact_id}")
def remove_circle_member(
    circle_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove a contact from a circle."""
    circle = db.query(Circle).filter(Circle.id == circle_id, Circle.user_id == user.id).first()
    if not circle:
        raise HTTPException(404, "Circle not found")

    member = db.query(CircleMember).filter(
        CircleMember.circle_id == circle_id,
        CircleMember.contact_id == contact_id,
    ).first()
    if not member:
        raise HTTPException(404, "Member not found")

    db.delete(member)
    db.commit()
    return {"status": "removed"}


@app.delete("/circles/{circle_id}")
def delete_circle(
    circle_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a circle."""
    circle = db.query(Circle).filter(Circle.id == circle_id, Circle.user_id == user.id).first()
    if not circle:
        raise HTTPException(404, "Circle not found")

    db.query(CircleQuest).filter(CircleQuest.circle_id == circle_id).delete()
    db.query(CircleMember).filter(CircleMember.circle_id == circle_id).delete()
    db.delete(circle)
    db.commit()
    return {"status": "deleted"}


@app.post("/circles/{circle_id}/quest")
def start_circle_quest(
    circle_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start a circle quest: interact with all members."""
    circle = db.query(Circle).filter(Circle.id == circle_id, Circle.user_id == user.id).first()
    if not circle:
        raise HTTPException(404, "Circle not found")

    # Check for existing active quest
    existing = db.query(CircleQuest).filter(
        CircleQuest.circle_id == circle_id,
        CircleQuest.status == "active",
    ).first()
    if existing:
        raise HTTPException(400, "Circle already has an active quest")

    cq = create_circle_quest(circle, user, db)
    if not cq:
        raise HTTPException(400, "Circle has no members")
    return cq


# ══════════════════════════════════════════════
# WEEKLY REPORT (protected)
# ══════════════════════════════════════════════

@app.get("/report/weekly")
def weekly_report(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a weekly activity report."""
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    # Interactions this week
    interactions_this_week = (
        db.query(func.count(Interaction.id))
        .filter(Interaction.user_id == user.id, Interaction.timestamp >= week_ago)
        .scalar() or 0
    )

    # Distinct contacts reached this week
    contacts_reached = (
        db.query(func.count(func.distinct(Interaction.contact_id)))
        .filter(Interaction.user_id == user.id, Interaction.timestamp >= week_ago)
        .scalar() or 0
    )

    # Gates cleared this week
    gates_cleared = (
        db.query(func.count(Gate.id))
        .filter(
            Gate.creator_id == user.id,
            Gate.status == "cleared",
            Gate.cleared_at >= week_ago,
        )
        .scalar() or 0
    )

    # Quests completed this week
    quests_completed = (
        db.query(func.count(Quest.id))
        .filter(
            Quest.user_id == user.id,
            Quest.status == QuestStatus.completed,
            Quest.completed_at >= week_ago,
        )
        .scalar() or 0
    )

    # Approximate XP earned this week (from interactions: ~20 XP avg per interaction)
    xp_estimated = interactions_this_week * 20

    return {
        "period": "weekly",
        "start": week_ago.isoformat(),
        "end": now.isoformat(),
        "interactions": interactions_this_week,
        "contacts_reached": contacts_reached,
        "gates_cleared": gates_cleared,
        "quests_completed": quests_completed,
        "xp_estimated": xp_estimated,
    }


# ══════════════════════════════════════════════
# CSV & DATA EXPORT / IMPORT (protected)
# ══════════════════════════════════════════════

@app.get("/contacts/export/csv")
def export_contacts_csv(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contacts = db.query(Contact).filter(Contact.user_id == user.id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name", "relationship_type", "target_frequency", "notes",
        "city", "relationship_xp", "relationship_level", "created_at",
    ])
    for c in contacts:
        writer.writerow([
            c.name,
            c.relationship_type.value if c.relationship_type else "",
            c.target_frequency.value if c.target_frequency else "",
            c.notes or "",
            c.city or "",
            c.relationship_xp or 0,
            c.relationship_level or 0,
            c.created_at.isoformat() if c.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orbit_contacts.csv"},
    )


@app.post("/contacts/import/csv")
@limiter.limit("5/hour")
def import_contacts_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file")

    try:
        contents = file.file.read().decode("utf-8")
    except Exception:
        raise HTTPException(400, "Could not read file. Ensure it is UTF-8 encoded CSV.")

    reader = csv.DictReader(io.StringIO(contents))
    required_columns = {"name"}
    if not required_columns.issubset(set(reader.fieldnames or [])):
        raise HTTPException(400, "CSV must contain at least a 'name' column")

    imported_count = 0
    errors = []
    for i, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        if not name:
            errors.append(f"Row {i}: missing name, skipped")
            continue

        relationship_type = (row.get("relationship_type") or "friend").strip().lower()
        frequency = (row.get("frequency") or row.get("target_frequency") or "monthly").strip().lower()
        notes = (row.get("notes") or "").strip()
        city = (row.get("city") or "").strip()

        try:
            contact = Contact(
                user_id=user.id,
                name=name,
                relationship_type=relationship_type,
                target_frequency=frequency,
                notes=notes or None,
                city=city or None,
            )
            db.add(contact)
            db.flush()

            weights = Weights(contact_id=contact.id)
            db.add(weights)
            imported_count += 1
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")
            db.rollback()
            continue

    db.commit()
    result = {"imported": imported_count}
    if errors:
        result["errors"] = errors
    return result


@app.get("/export/data")
def export_all_user_data(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from .models import UserAchievement

    contacts = db.query(Contact).filter(Contact.user_id == user.id).all()
    interactions = db.query(Interaction).filter(Interaction.user_id == user.id).all()

    contact_ids = [c.id for c in contacts]
    life_events = (
        db.query(LifeEvent).filter(LifeEvent.contact_id.in_(contact_ids)).all()
        if contact_ids else []
    )
    achievements = (
        db.query(UserAchievement).filter(UserAchievement.user_id == user.id).all()
    )

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "xp": user.xp or 0,
            "level": user.level or 1,
            "exported_at": datetime.utcnow().isoformat(),
        },
        "contacts": [
            {
                "id": c.id,
                "name": c.name,
                "relationship_type": c.relationship_type.value if c.relationship_type else None,
                "target_frequency": c.target_frequency.value if c.target_frequency else None,
                "notes": c.notes,
                "city": c.city,
                "relationship_xp": c.relationship_xp or 0,
                "relationship_level": c.relationship_level or 0,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in contacts
        ],
        "interactions": [
            {
                "id": ix.id,
                "contact_id": ix.contact_id,
                "interaction_type": ix.interaction_type.value if ix.interaction_type else None,
                "duration_minutes": ix.duration_minutes,
                "initiated_by_user": ix.initiated_by_user,
                "notes": ix.notes,
                "quality_score": ix.quality_score,
                "timestamp": ix.timestamp.isoformat() if ix.timestamp else None,
            }
            for ix in interactions
        ],
        "life_events": [
            {
                "id": le.id,
                "contact_id": le.contact_id,
                "event_type": le.event_type,
                "description": le.description,
                "event_date": le.event_date.isoformat() if le.event_date else None,
                "pause_decay": le.pause_decay,
            }
            for le in life_events
        ],
        "achievements": [
            {
                "achievement_key": ua.achievement_key,
                "earned_at": ua.earned_at.isoformat() if ua.earned_at else None,
            }
            for ua in achievements
        ],
    }


# ══════════════════════════════════════════════
# FRONTEND (serves index.html at root if present)
# When deployed as monolith: index.html sits alongside backend/
# When API-only mode: returns JSON health check instead
# ══════════════════════════════════════════════

_STATIC_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_PATH = _STATIC_ROOT / "index.html"
MANIFEST_PATH = _STATIC_ROOT / "manifest.json"
SW_PATH = _STATIC_ROOT / "sw.js"


@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(MANIFEST_PATH, media_type="application/manifest+json")


@app.get("/sw.js")
def serve_sw():
    return FileResponse(SW_PATH, media_type="application/javascript")


@app.get("/icon-192.png")
def serve_icon_192():
    return FileResponse(_STATIC_ROOT / "icon-192.png", media_type="image/png")


@app.get("/icon-512.png")
def serve_icon_512():
    return FileResponse(_STATIC_ROOT / "icon-512.png", media_type="image/png")


@app.get("/icon-180.png")
def serve_icon_180():
    return FileResponse(_STATIC_ROOT / "icon-180.png", media_type="image/png")


@app.get("/native-bridge.js")
def serve_native_bridge():
    path = _STATIC_ROOT / "native-bridge.js"
    if path.exists():
        return FileResponse(path, media_type="application/javascript")
    return JSONResponse(content={}, status_code=404)


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Health check for monitoring and load balancers."""
    try:
        db.execute(func.now())
        return {"status": "healthy", "service": "Orbit API", "version": "0.3.0"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unhealthy"})


@app.get("/verify")
def serve_verify():
    """Email verification landing page."""
    if FRONTEND_PATH.exists():
        return FileResponse(FRONTEND_PATH, media_type="text/html")
    return {"message": "Verify your email at the Orbit app"}

@app.get("/reset-password")
def serve_reset_password():
    """Password reset landing page."""
    if FRONTEND_PATH.exists():
        return FileResponse(FRONTEND_PATH, media_type="text/html")
    return {"message": "Reset your password at the Orbit app"}

@app.get("/privacy")
def serve_privacy():
    """Standalone privacy policy page for app store listings."""
    if FRONTEND_PATH.exists():
        return FileResponse(FRONTEND_PATH, media_type="text/html")
    return {"message": "Privacy Policy — contact privacy@orbitapp.io"}

@app.get("/terms")
def serve_terms():
    """Standalone terms of service page for app store listings."""
    if FRONTEND_PATH.exists():
        return FileResponse(FRONTEND_PATH, media_type="text/html")
    return {"message": "Terms of Service — contact legal@orbitapp.io"}

@app.get("/")
def serve_frontend():
    if FRONTEND_PATH.exists():
        return FileResponse(FRONTEND_PATH, media_type="text/html")
    return {"status": "ok", "service": "Orbit API", "version": "0.3.0"}
