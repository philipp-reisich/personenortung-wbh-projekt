# path: personenortung-wbh-projekt/api/auth.py
"""Authentication and authorization utilities using JWT and Argon2.

This module encapsulates user password hashing, token creation and verification,
and role-based access control. Users are stored in the database table `users`
with the columns `uid`, `username`, `password_hash`, `role`, and timestamps.
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
import asyncpg

from .config import get_settings
from .db import get_db_connection


pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

bearer_scheme = HTTPBearer()


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(
    *, subject: str, role: str, expires_delta: Optional[timedelta] = None
) -> str:
    """Create a signed JWT for the given subject and role.

    :param subject: Unique identifier for the user (e.g. username or uid).
    :param role: The role assigned to the user (admin, operator, viewer).
    :param expires_delta: Duration after which the token expires.
    :return: Encoded JWT string.
    """
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(hours=settings.token_lifetime_hours)
    expire = datetime.utcnow() + expires_delta
    payload = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
    return token


async def authenticate_user(
    username: str, password: str, conn: asyncpg.Connection
) -> Tuple[str, str]:
    """Validate the given username and password and return (uid, role).

    Raises HTTPException if authentication fails.
    """
    row = await conn.fetchrow(
        "SELECT uid, password_hash, role FROM users WHERE username=$1",
        username,
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    uid, password_hash, role = row["uid"], row["password_hash"], row["role"]
    if not verify_password(password, password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    return uid, role


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    conn: asyncpg.Connection = Depends(get_db_connection),
) -> Tuple[str, str]:
    """FastAPI dependency that extracts and validates a JWT.

    Returns a tuple of (uid, role). If verification fails, an HTTP 401 is raised.
    """
    token = credentials.credentials
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    uid = payload.get("sub")
    role = payload.get("role")
    if uid is None or role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
        )
    # Optionally verify the user still exists
    row = await conn.fetchrow("SELECT uid, role FROM users WHERE uid=$1", uid)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    return uid, role
