"""
Email + password auth. Added 2026-11-14 per Jeff ("Instead of auth, let's
just use a simple email and password system") after the Cost Tracker /
settings-page conversation flagged that main.py had zero auth and
`allow_origins=["*"]` -- fine for a read-only local triage tool, not fine
once a settings page can write API keys and DATABASE_URL.

Decided scope (AskUserQuestion, 2026-11-14):
  - Protects the WHOLE app, not just the new settings page -- enforced by
    a middleware in main.py, not per-route Depends, so nothing already
    built (accounts, cost-tracker, enrichment dispatch, etc.) needs
    individual edits.
  - Multi-user with sign-up (not one fixed admin account) -- a real
    `users` table (models.User), not an env-var credential.

Design:
  - Passwords hashed with bcrypt (not rolled by hand, not MD5/SHA -- bcrypt
    is a real, slow, salted KDF built for this).
  - Sessions are JWTs (PyJWT, already installed in this environment;
    bcrypt added to requirements.txt alongside PyJWT since neither was
    there before). A JWT (not a server-side session table) was chosen
    because the frontend is a separate-origin SPA talking to this API
    over bare CORS, not cookie-based same-site requests -- a bearer token
    in an Authorization header avoids SameSite/cross-origin cookie
    complications entirely.
  - JWT_SECRET_KEY: read from env; if absent, generated once and
    persisted to whichever .env main.py already loads from (same file
    search order), so sessions survive a restart instead of invalidating
    every token on every process restart. Logged clearly so Jeff knows a
    secret was auto-generated rather than silently guessing he'd never
    notice.
"""

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from . import models

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week -- solo/small-team local tool, not worth frequent re-logins

# Same two candidate .env paths main.py already searches (local backend
# .env first, then the workers' .env) -- write the generated secret to
# whichever one of those exists, or create the local one if neither does,
# so this doesn't introduce a THIRD place secrets can live.
_LOCAL_ENV = Path(__file__).parent / ".env"
_WORKERS_ENV = Path(__file__).parent.parent.parent / "MPLC" / "production" / "workers" / ".env"


def _persist_generated_secret(secret: str) -> Path:
    target = _LOCAL_ENV if _LOCAL_ENV.exists() else (_WORKERS_ENV if _WORKERS_ENV.exists() else _LOCAL_ENV)
    with open(target, "a") as f:
        f.write(f"\nJWT_SECRET_KEY={secret}\n")
    return target


def _get_secret_key() -> str:
    key = os.getenv("JWT_SECRET_KEY")
    if key:
        return key
    generated = secrets.token_hex(32)
    path = _persist_generated_secret(generated)
    print(
        f"[auth] No JWT_SECRET_KEY set -- generated one and wrote it to {path}. "
        f"Restart will now reuse it. If you run this on another machine, copy "
        f"that value over or every existing login session will be invalidated.",
        flush=True,
    )
    os.environ["JWT_SECRET_KEY"] = generated  # so the REST of this process run uses it immediately too
    return generated


SECRET_KEY = _get_secret_key()

# Paths that don't require a valid token -- everything else in the app is
# protected by the middleware in main.py. Kept here (not in main.py) so
# the exemption list lives next to the code that enforces it.
EXEMPT_PATHS = {"/auth/signup", "/auth/login", "/health"}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "email": email, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


class InvalidToken(Exception):
    pass


def decode_access_token(token: str) -> dict:
    """Raises InvalidToken on anything wrong (expired, bad signature,
    malformed) -- callers decide how to respond (middleware: 401 JSON;
    Depends-based dependency: HTTPException), this just never lets a bad
    token through silently."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as e:
        raise InvalidToken(str(e))


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[len("Bearer "):]


def authenticate_request(authorization: Optional[str], db: Session) -> Optional[models.User]:
    """Used by both the middleware (whole-app enforcement) and the
    Depends-based get_current_user (for handlers that need the actual
    User object, e.g. /auth/me) -- one real implementation, not two."""
    token = _extract_bearer_token(authorization)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except InvalidToken:
        return None
    user = db.get(models.User, payload.get("sub"))
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    """Depends-based accessor for handlers that need the User object
    itself (not just "is this request authorized", which the middleware
    already enforced before the handler runs). Re-checks rather than
    trusting request.state, since relying on middleware-set state here
    would make this dependency's correctness depend on middleware
    ordering -- cheap to just re-verify."""
    user = authenticate_request(request.headers.get("authorization"), db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def new_user_id() -> str:
    return str(uuid.uuid4())
