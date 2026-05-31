"""
services/auth_service.py — Authentication with Redis-backed sessions

Updated from Module 3 stub to include:
  - Storing refresh token hash in Redis on login
  - Validating refresh token against Redis on refresh
  - True logout via Redis session deletion
"""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import TokenResponse, UserRegister


def _hash_token(token: str) -> str:
    """
    SHA-256 hash a token for storage.

    WHY hash refresh tokens before storing in Redis?
      If Redis is breached, attackers get SHA-256 hashes, not usable tokens.
      SHA-256 is fine here (not bcrypt) because:
        - Tokens are already high-entropy random strings — no dictionary attack possible
        - We only verify by hashing the presented token and comparing — fast is fine
        - bcrypt's slowness is for low-entropy passwords — overkill here

    This is the same reason GitHub stores API token hashes, not the tokens themselves.
    """
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, db: AsyncSession, cache=None):
        self.db = db
        self.cache = cache   # CacheService — optional, None in tests without Redis

    async def register(self, data: UserRegister) -> User:
        """Register a new user."""
        from fastapi import HTTPException, status

        existing = await self.db.execute(select(User).where(User.email == data.email))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists",
            )

        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
        )
        self.db.add(user)
        await self.db.flush()
        return user

    async def login(self, email: str, password: str) -> TokenResponse:
        """Authenticate and issue tokens. Store refresh token hash in Redis."""
        from fastapi import HTTPException, status

        invalid = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user is None:
            verify_password("dummy_plain", "$2b$12$UhYkr0rau2Lwc/BNs6kAsOvBuwZj9ONJLeRyl2q3JkGkjT/UYC6b.")
            raise invalid

        if not verify_password(password, user.hashed_password):
            raise invalid

        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")

        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)

        # Store refresh token hash in Redis — enables true logout
        if self.cache:
            await self.cache.store_refresh_token(user.id, _hash_token(refresh_token))

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        """
        Exchange a refresh token for a new access token.

        Enhanced: validates the token against the Redis-stored hash.
        This means logout truly invalidates the refresh token.
        """
        from fastapi import HTTPException, status
        from jose import JWTError
        from app.core.security import decode_token

        try:
            payload = decode_token(refresh_token)
            if payload.get("type") != "refresh":
                raise ValueError("Not a refresh token")
            user_id = uuid.UUID(payload["sub"])
        except (JWTError, ValueError, KeyError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        # Validate against Redis if cache is available
        if self.cache:
            stored_hash = await self.cache.get_refresh_token_hash(user_id)
            if stored_hash is None or stored_hash != _hash_token(refresh_token):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token has been revoked",
                )

        user = await self.db.get(User, user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

        new_access = create_access_token(user.id)
        return TokenResponse(access_token=new_access, refresh_token=refresh_token)

    async def logout(self, user_id: uuid.UUID) -> None:
        """
        True logout — revoke the Redis session.

        After this call, the user's refresh token is invalid even if it
        hasn't expired. The access token still works until its 30-minute
        TTL, which is acceptable (see JWT Module discussion on denylist).
        """
        if self.cache:
            await self.cache.revoke_session(user_id)
