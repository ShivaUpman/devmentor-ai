"""
core/dependencies.py — FastAPI dependency injection

WHY dependency injection?
  Instead of repeating auth logic in every endpoint, we define it once
  and "inject" it wherever needed. FastAPI calls the dependency function
  automatically, before your endpoint runs.

  Without DI — the naive way:
    @app.get("/profile")
    async def profile(token: str = Header(...)):
        # Auth logic repeated in every endpoint
        payload = decode_token(token)
        user = await db.get(User, payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(401)
        # Now do the actual work...

  With DI — the FastAPI way:
    @app.get("/profile")
    async def profile(current_user: User = Depends(get_current_user)):
        # current_user is already verified and fetched
        return current_user

  Industry usage: Spring (Java), ASP.NET Core, Angular all use DI extensively.
  It's the foundation of testable, maintainable backend code.

Interview question: "How does FastAPI's dependency injection work?"
Answer: FastAPI inspects the function signature. Any parameter typed with
  Depends(...) is resolved before the endpoint runs. Dependencies can have
  their own dependencies (a graph). FastAPI resolves the full graph,
  calls them in order, and injects results. Async dependencies run concurrently.
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User

# ── Token extractor ────────────────────────────────────────────────────────────
# HTTPBearer extracts the token from the Authorization header.
# It expects: "Authorization: Bearer <token>"
# auto_error=False: we return None instead of raising 403 when header is missing.
#   This lets us handle the error ourselves with a better message.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Core auth dependency — resolves a Bearer token to a User object.

    Flow:
      1. Extract token from Authorization header
      2. Verify JWT signature and expiry
      3. Extract user UUID from payload
      4. Fetch User from database (ensures user still exists and is active)
      5. Return the User — endpoint receives it already validated

    WHY fetch from DB every request even though JWT is stateless?
      To handle account deactivation. If we ban a user, their JWT is still
      cryptographically valid. Fetching from DB ensures:
        - User still exists (wasn't deleted)
        - User is still active (wasn't banned)
      
      Tradeoff: one DB query per authenticated request.
      At scale: cache the user object in Redis for 60 seconds to reduce DB load.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        # WWW-Authenticate tells the client HOW to authenticate.
        # Required by HTTP spec for 401 responses. Clients use it to trigger
        # login UI or retry with a different auth scheme.
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    try:
        payload = decode_token(credentials.credentials)

        user_id_str: str | None = payload.get("sub")
        token_type: str | None = payload.get("type")

        if user_id_str is None or token_type != "access":
            # Reject if: missing sub, OR it's a refresh token used as access token
            raise credentials_exception

        user_id = uuid.UUID(user_id_str)

    except (JWTError, ValueError):
        # JWTError: expired, invalid signature, malformed
        # ValueError: sub wasn't a valid UUID string
        raise credentials_exception

    # Fetch from DB — confirms user exists and is active
    user = await db.get(User, user_id)

    if user is None or not user.is_active:
        raise credentials_exception

    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Admin-only dependency — composed on top of get_current_user.

    WHY compose dependencies?
      get_current_admin reuses get_current_user — it doesn't re-implement auth.
      It just adds an authorization check on top.

      Authentication = who are you? (JWT)
      Authorization  = what are you allowed to do? (role check)

      These are deliberately separate concepts with separate layers.
      Common interview mistake: conflating authentication with authorization.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
            # 403 Forbidden ≠ 401 Unauthorized
            # 401: I don't know who you are (not authenticated)
            # 403: I know who you are, but you can't do this (not authorized)
        )
    return current_user


# ── Optional auth dependency ───────────────────────────────────────────────────
async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """
    Returns the user if authenticated, None if not.

    Used for endpoints that work for both guests and logged-in users —
    e.g., a public question bank that shows extra features when logged in.
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None
