"""
Authentication module — JWT tokens + invite-code registration.

Endpoints:
    POST /api/auth/register  — create account (requires invite code)
    POST /api/auth/login     — returns JWT access token
    GET  /api/auth/me        — current user info

Guards:
    require_user  — any authenticated user
    require_admin — admin-only (refresh, user management)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import hashlib
import secrets

from jose import JWTError, jwt
from pydantic import BaseModel

from src import database

# ---------------------------------------------------------------------------
# Config (reads from env, with safe defaults for local dev)
# ---------------------------------------------------------------------------

SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 72  # 3 days — long-lived for a small app
INVITE_CODE: str = os.getenv("INVITE_CODE", "pickaparlay2026")

# ---------------------------------------------------------------------------
# Password hashing (PBKDF2-SHA256 — stdlib, no bcrypt version issues)
# ---------------------------------------------------------------------------

_HASH_ITERATIONS = 600_000  # OWASP recommended minimum

def hash_password(plain: str) -> str:
    """Hash a password with a random salt using PBKDF2-SHA256."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), _HASH_ITERATIONS)
    return f"{salt}${h.hex()}"

def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        salt, stored_hash = hashed.split("$", 1)
        h = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), _HASH_ITERATIONS)
        return secrets.compare_digest(h.hex(), stored_hash)
    except (ValueError, AttributeError):
        return False

# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: int, username: str, is_admin: bool) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises JWTError on failure."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def require_user(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    """Dependency: returns user dict or raises 401."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
        user = database.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except (JWTError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_admin(user: dict = Depends(require_user)) -> dict:
    """Dependency: returns admin user dict or raises 403."""
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def optional_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[dict]:
    """Dependency: returns user dict or None (no error if unauthenticated)."""
    if token is None:
        return None
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
        return database.get_user_by_id(user_id)
    except (JWTError, KeyError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    invite_code: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    display_name: Optional[str]
    is_admin: bool


# ---------------------------------------------------------------------------
# Auth router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest):
    """Create a new account. Requires a valid invite code."""
    # Validate invite code
    if req.invite_code != INVITE_CODE:
        raise HTTPException(status_code=403, detail="Invalid invite code")

    # Validate input
    username = req.username.strip().lower()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    # Check if username taken
    existing = database.get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    # First user is auto-admin
    user_count = database.get_user_count()
    is_admin = user_count == 0

    # Create user
    password_hash = hash_password(req.password)
    user_id = database.create_user(
        username=username,
        password_hash=password_hash,
        display_name=req.display_name or username,
        is_admin=is_admin,
    )

    # Return token
    token = create_access_token(user_id, username, is_admin)
    return TokenResponse(
        access_token=token,
        user_id=user_id,
        username=username,
        display_name=req.display_name or username,
        is_admin=is_admin,
    )


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    """Authenticate and receive a JWT token."""
    username = req.username.strip().lower()
    user = database.get_user_by_username(username)

    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(user["id"], user["username"], bool(user["is_admin"]))
    return TokenResponse(
        access_token=token,
        user_id=user["id"],
        username=user["username"],
        display_name=user.get("display_name") or user["username"],
        is_admin=bool(user["is_admin"]),
    )


@router.get("/me")
def me(user: dict = Depends(require_user)):
    """Return current user info."""
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name"),
        "is_admin": bool(user["is_admin"]),
        "created_at": user.get("created_at"),
    }
