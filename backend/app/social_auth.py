"""
Social authentication for Orbit.

Verifies ID tokens from Apple and Google, returning the user's
email, name, and provider-specific user ID.
"""

import os
import logging
from typing import Optional
import httpx
from jose import jwt, JWTError

log = logging.getLogger("orbit.social_auth")

# ── Config ──

APPLE_CLIENT_ID = os.environ.get("APPLE_CLIENT_ID", "io.orbitapp.app")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"

# Cache Apple's JWKS keys in memory
_apple_jwks_cache: Optional[dict] = None


async def _get_apple_jwks() -> dict:
    """Fetch Apple's public keys (JWKS) for token verification."""
    global _apple_jwks_cache
    if _apple_jwks_cache:
        return _apple_jwks_cache

    async with httpx.AsyncClient() as client:
        resp = await client.get(APPLE_JWKS_URL, timeout=10)
        resp.raise_for_status()
        _apple_jwks_cache = resp.json()
        return _apple_jwks_cache


async def verify_apple_token(id_token: str) -> dict:
    """
    Verify an Apple ID token and return user info.

    Returns: {"sub": "...", "email": "...", "email_verified": bool}
    Raises: ValueError on invalid token.
    """
    try:
        # Get the key ID from the token header
        header = jwt.get_unverified_header(id_token)
        kid = header.get("kid")
        if not kid:
            raise ValueError("Token missing kid header")

        # Fetch Apple's public keys
        jwks = await _get_apple_jwks()
        key = None
        for k in jwks.get("keys", []):
            if k["kid"] == kid:
                key = k
                break

        if not key:
            # Invalidate cache and retry once (Apple may have rotated keys)
            global _apple_jwks_cache
            _apple_jwks_cache = None
            jwks = await _get_apple_jwks()
            for k in jwks.get("keys", []):
                if k["kid"] == kid:
                    key = k
                    break

        if not key:
            raise ValueError("No matching Apple public key found")

        # Decode and verify the token
        payload = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=APPLE_CLIENT_ID,
            issuer="https://appleid.apple.com",
        )

        email = payload.get("email")
        if not email:
            raise ValueError("Token missing email claim")

        return {
            "sub": payload["sub"],
            "email": email,
            "email_verified": payload.get("email_verified", False),
        }

    except JWTError as e:
        log.warning("Apple token verification failed: %s", e)
        raise ValueError(f"Invalid Apple ID token: {e}")


async def verify_google_token(id_token: str) -> dict:
    """
    Verify a Google ID token and return user info.

    Uses Google's tokeninfo endpoint for simplicity and reliability.
    Returns: {"sub": "...", "email": "...", "name": "...", "email_verified": bool}
    Raises: ValueError on invalid token.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                GOOGLE_TOKENINFO_URL,
                params={"id_token": id_token},
                timeout=10,
            )

            if resp.status_code != 200:
                raise ValueError("Google token verification failed")

            payload = resp.json()

        # Verify the audience matches our client ID
        aud = payload.get("aud", "")
        if GOOGLE_CLIENT_ID and aud != GOOGLE_CLIENT_ID:
            raise ValueError("Token audience mismatch")

        email = payload.get("email")
        if not email:
            raise ValueError("Token missing email")

        return {
            "sub": payload["sub"],
            "email": email,
            "name": payload.get("name", ""),
            "email_verified": payload.get("email_verified", "false") == "true",
        }

    except httpx.HTTPError as e:
        log.warning("Google token verification failed: %s", e)
        raise ValueError(f"Failed to verify Google token: {e}")
