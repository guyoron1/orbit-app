"""
Push Notification Service for Orbit.

Sends push notifications via Firebase Cloud Messaging (FCM) HTTP v1 API.
Falls back to console logging when no Firebase credentials are configured.

Setup:
  1. Create a Firebase project at https://console.firebase.google.com
  2. Download service account JSON from Project Settings > Service Accounts
  3. Set FIREBASE_CREDENTIALS_JSON env var (the JSON string, not a file path)
  4. For iOS: upload APNs key to Firebase > Project Settings > Cloud Messaging
"""

import os
import json
import time
import logging
from typing import Optional

log = logging.getLogger("orbit.push")

FIREBASE_CREDENTIALS_JSON = os.environ.get("FIREBASE_CREDENTIALS_JSON", "")
_fcm_access_token: Optional[str] = None
_fcm_token_expires: float = 0
_firebase_project_id: Optional[str] = None


def _get_firebase_config() -> Optional[dict]:
    """Parse Firebase service account credentials."""
    if not FIREBASE_CREDENTIALS_JSON:
        return None
    try:
        return json.loads(FIREBASE_CREDENTIALS_JSON)
    except json.JSONDecodeError:
        log.error("Invalid FIREBASE_CREDENTIALS_JSON — could not parse as JSON")
        return None


def _get_fcm_access_token() -> Optional[str]:
    """Get an OAuth2 access token for FCM using service account credentials."""
    global _fcm_access_token, _fcm_token_expires, _firebase_project_id

    if _fcm_access_token and time.time() < _fcm_token_expires:
        return _fcm_access_token

    creds = _get_firebase_config()
    if not creds:
        return None

    _firebase_project_id = creds.get("project_id")

    try:
        import jwt as pyjwt
        now = int(time.time())
        payload = {
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now,
            "exp": now + 3600,
        }
        signed_jwt = pyjwt.encode(payload, creds["private_key"], algorithm="RS256")

        import httpx
        resp = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": signed_jwt,
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            _fcm_access_token = data["access_token"]
            _fcm_token_expires = now + data.get("expires_in", 3500) - 60
            return _fcm_access_token
        else:
            log.error("FCM token exchange failed: %s", resp.text)
            return None
    except ImportError:
        log.error("PyJWT is required for FCM. Install with: pip install PyJWT")
        return None
    except Exception as e:
        log.error("FCM auth error: %s", e)
        return None


async def send_push(
    token: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
    badge: Optional[int] = None,
) -> bool:
    """
    Send a push notification to a single device.

    Args:
        token: FCM device registration token
        title: Notification title
        body: Notification body text
        data: Optional data payload (key-value pairs for the app)
        badge: Optional badge count for iOS

    Returns:
        True if sent successfully, False otherwise
    """
    access_token = _get_fcm_access_token()

    if not access_token or not _firebase_project_id:
        log.info("[PUSH-LOG] TO: %s | TITLE: %s | BODY: %s | DATA: %s",
                 token[:20] + "...", title, body, data)
        return True  # Log mode — pretend success

    import httpx

    message: dict = {
        "message": {
            "token": token,
            "notification": {
                "title": title,
                "body": body,
            },
        }
    }

    if data:
        message["message"]["data"] = {k: str(v) for k, v in data.items()}

    # iOS-specific config
    message["message"]["apns"] = {
        "headers": {
            "apns-priority": "10",
        },
        "payload": {
            "aps": {
                "sound": "default",
                "badge": badge or 0,
            }
        }
    }

    # Android-specific config
    message["message"]["android"] = {
        "priority": "high",
        "notification": {
            "sound": "default",
            "channel_id": "orbit_nudges",
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://fcm.googleapis.com/v1/projects/{_firebase_project_id}/messages:send",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=message,
            )
            if resp.status_code == 200:
                return True
            elif resp.status_code == 404:
                # Token is invalid/expired — mark for cleanup
                log.warning("FCM token invalid (404): %s", token[:20])
                return False
            else:
                log.error("FCM send error: %s %s", resp.status_code, resp.text)
                return False
    except Exception as e:
        log.error("FCM send exception: %s", e)
        return False


async def send_push_to_user(
    db,
    user_id: int,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> int:
    """
    Send a push notification to all active devices of a user.

    Returns the number of successfully sent notifications.
    """
    from .models import PushToken

    tokens = (
        db.query(PushToken)
        .filter(PushToken.user_id == user_id, PushToken.active == True)
        .all()
    )

    if not tokens:
        return 0

    sent = 0
    for pt in tokens:
        success = await send_push(
            token=pt.token,
            title=title,
            body=body,
            data=data,
        )
        if success:
            sent += 1
        else:
            # Mark invalid token as inactive
            pt.active = False
            db.commit()

    return sent
