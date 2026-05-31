"""
api/v1/endpoints/auth.py — Authentication HTTP endpoints

WHY keep endpoints so thin?
  The endpoint's only jobs are:
    1. Receive and validate the HTTP request (Pydantic does this)
    2. Call the appropriate service function
    3. Return an HTTP response

  Business logic belongs in the service. DB queries belong in the service.
  The endpoint is the "controller" in MVC — just wiring, not logic.

  This makes endpoints:
    - Trivially testable (mock the service, not the DB)
    - Easy to change (swap the transport layer without touching business logic)
    - Readable at a glance (< 30 lines per endpoint)

REST API design principles applied here:
  POST /auth/register  — create a resource (new user)
  POST /auth/login     — action (not a resource, but POST is conventional for auth)
  POST /auth/refresh   — action
  GET  /auth/me        — read current user's own resource

Status codes:
  201 Created — user was created
  200 OK      — login/refresh succeeded
  401 Unauthorized — bad credentials
  409 Conflict — email already taken
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import TokenResponse, UserLogin, UserRegister, UserResponse
from app.services.auth_service import AuthService

router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(
    data: UserRegister,           # Pydantic validates + parses request body
    db: AsyncSession = Depends(get_db),  # DB session injected
) -> UserResponse:
    """
    Create a new user account.

    - Validates email format and password strength via Pydantic
    - Hashes password with bcrypt
    - Returns the created user (without the hashed password)
    """
    service = AuthService(db)
    user = await service.register(data)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and receive JWT tokens",
)
async def login(
    data: UserLogin,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Authenticate with email and password.

    Returns:
    - `access_token`: short-lived (30 min), send in Authorization header
    - `refresh_token`: long-lived (7 days), use to get new access tokens
    - `token_type`: always "bearer"

    Usage: `Authorization: Bearer <access_token>`
    """
    service = AuthService(db)
    return await service.login(data.email, data.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange refresh token for new access token",
)
async def refresh(
    # WHY a simple dict body here instead of a schema?
    #   The refresh endpoint receives just one field. A full Pydantic schema
    #   is overkill. In a real project we'd still use a schema for consistency.
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Use a refresh token to get a new access token without re-entering credentials.
    """
    refresh_token = body.get("refresh_token", "")
    service = AuthService(db)
    return await service.refresh(refresh_token)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user",
)
async def get_me(
    current_user: User = Depends(get_current_user),  # Auth enforced here
) -> UserResponse:
    """
    Returns the profile of the currently authenticated user.

    This endpoint demonstrates the dependency injection pattern:
    `get_current_user` is called automatically by FastAPI before this function
    runs. If the token is invalid, FastAPI returns 401 before we're invoked.
    """
    return UserResponse.model_validate(current_user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout (client-side token discard)",
)
async def logout(
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Stateless logout — the client must discard their tokens.

    WHY can't we truly invalidate a JWT server-side?
      JWTs are stateless — no server state tracks them.
      True logout requires a "token denylist" in Redis:
        1. On logout, add the token's JTI (JWT ID) to Redis with TTL = token expiry
        2. On every request, check Redis for the JTI before accepting the token
      This re-introduces statefulness but enables true revocation.

      For production: implement this with Redis. For MVP: client-side discard.

    Returns 204 No Content — success with no response body.
    The client should delete both tokens from local storage/cookies.
    """
    # In production: add current token's JTI to Redis denylist
    # redis_client.setex(f"denylist:{jti}", ACCESS_TOKEN_EXPIRE_MINUTES * 60, "1")
    return None
