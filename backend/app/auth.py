"""
JWT Authentication for Orbit.

Provides:
  - Password hashing with bcrypt
  - JWT token creation and validation
  - Email verification & password reset tokens
  - Email sending (Resend API or console fallback)
  - FastAPI dependency for protected routes
"""

import os
import logging
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

log = logging.getLogger("orbit.auth")

# ── Config ──
SECRET_KEY = os.environ.get("JWT_SECRET", "")
if not SECRET_KEY:
    import warnings
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("PORT"):
        raise RuntimeError("JWT_SECRET must be set in production. Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    SECRET_KEY = "orbit-local-dev-only-not-for-production"
    warnings.warn("Using insecure default JWT_SECRET — set JWT_SECRET env var for production", stacklevel=1)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("TOKEN_EXPIRE_MINUTES", "1440"))  # 24h default

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
APP_URL = os.environ.get("APP_URL", "https://orbit-app-production-fd37.up.railway.app")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "Orbit <noreply@orbitapp.io>")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Password utils ──

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── Token utils ──

def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_verification_token(user_id: int, email: str) -> str:
    """Create a short-lived token for email verification (24h)."""
    expire = datetime.utcnow() + timedelta(hours=24)
    payload = {
        "sub": str(user_id),
        "email": email,
        "purpose": "verify",
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_reset_token(user_id: int, email: str) -> str:
    """Create a short-lived token for password reset (1h)."""
    expire = datetime.utcnow() + timedelta(hours=1)
    payload = {
        "sub": str(user_id),
        "email": email,
        "purpose": "reset",
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_purpose_token(token: str, expected_purpose: str) -> dict:
    """Decode a token and verify its purpose claim."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(400, "Invalid or expired token")
    if payload.get("purpose") != expected_purpose:
        raise HTTPException(400, "Invalid token type")
    return payload


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Email sending ──

async def send_email(to: str, subject: str, html: str):
    """Send email via Resend API, or log to console if no API key."""
    if not RESEND_API_KEY:
        log.warning("No RESEND_API_KEY set — logging email instead of sending")
        log.info("TO: %s | SUBJECT: %s", to, subject)
        log.info("BODY: %s", html)
        return

    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={
                "from": FROM_EMAIL,
                "to": [to],
                "subject": subject,
                "html": html,
            },
        )
        if resp.status_code not in (200, 201):
            log.error("Failed to send email: %s %s", resp.status_code, resp.text)


async def send_verification_email(user_id: int, email: str, name: str):
    """Send email verification link."""
    token = create_verification_token(user_id, email)
    link = f"{APP_URL}/verify?token={token}"
    html = f"""
    <div style="font-family:Inter,system-ui,sans-serif;max-width:480px;margin:0 auto;padding:40px 20px;">
      <h2 style="color:#6c5ce7;margin-bottom:8px;">Welcome to Orbit!</h2>
      <p>Hi {name},</p>
      <p>Please verify your email address to get the most out of Orbit.</p>
      <a href="{link}" style="display:inline-block;background:#6c5ce7;color:white;padding:12px 32px;
         border-radius:8px;text-decoration:none;font-weight:600;margin:20px 0;">
        Verify Email
      </a>
      <p style="font-size:13px;color:#888;">Or copy this link: {link}</p>
      <p style="font-size:12px;color:#aaa;margin-top:30px;">This link expires in 24 hours.</p>
    </div>
    """
    await send_email(email, "Verify your Orbit email", html)


async def send_reset_email(user_id: int, email: str, name: str):
    """Send password reset link."""
    token = create_reset_token(user_id, email)
    link = f"{APP_URL}/reset-password?token={token}"
    html = f"""
    <div style="font-family:Inter,system-ui,sans-serif;max-width:480px;margin:0 auto;padding:40px 20px;">
      <h2 style="color:#6c5ce7;margin-bottom:8px;">Reset Your Password</h2>
      <p>Hi {name},</p>
      <p>We received a request to reset your Orbit password. Click below to choose a new one.</p>
      <a href="{link}" style="display:inline-block;background:#6c5ce7;color:white;padding:12px 32px;
         border-radius:8px;text-decoration:none;font-weight:600;margin:20px 0;">
        Reset Password
      </a>
      <p style="font-size:13px;color:#888;">Or copy this link: {link}</p>
      <p style="font-size:12px;color:#aaa;margin-top:30px;">This link expires in 1 hour. If you didn't request this, you can safely ignore it.</p>
    </div>
    """
    await send_email(email, "Reset your Orbit password", html)


# ── FastAPI dependency ──

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency that extracts and validates the current user from JWT."""
    payload = decode_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user
