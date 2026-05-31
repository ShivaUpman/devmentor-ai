"""
core/security.py — Password hashing and JWT token operations

WHY is this in core/ and not in a service or endpoint?
  This is pure cryptographic logic — no database, no HTTP, no business rules.
  It belongs in core/ because any module can import it without circular imports.
  Services call this. Endpoints don't touch crypto directly.

  Good architecture = each layer only imports from layers below it:
    endpoints → services → core
  Never: core → services → endpoints (circular)
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


# ── Password hashing ───────────────────────────────────────────────────────────
# WHY CryptContext instead of calling bcrypt directly?
#   CryptContext is a future-proof wrapper. If we ever need to migrate from
#   bcrypt to argon2 (the current recommended algo), we change one line here.
#   All existing hashes still verify correctly during the transition.
#
# WHY bcrypt and not SHA-256 or MD5?
#   SHA-256/MD5 are FAST — they can hash billions of passwords per second on GPU.
#   bcrypt is SLOW by design — it has a "work factor" (rounds) that limits
#   brute-force to thousands of attempts per second.
#   As hardware gets faster, you increase the work factor. MD5 can't do this.
#
# deprecated="auto": if a hash was created with an old algorithm/work factor,
#   passlib automatically marks it for rehashing on next login.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
BCRYPT_MAX_PASSWORD_BYTES = 72


def password_exceeds_bcrypt_limit(plain_password: str) -> bool:
    """Return whether a password is too large for bcrypt to process safely."""
    return len(plain_password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES


def hash_password(plain_password: str) -> str:
    """
    Hash a plain password using bcrypt.

    Output is always 60 characters — a bcrypt hash looks like:
      $2b$12$<22-char-salt><31-char-hash>
      $2b$ = bcrypt identifier
      12   = work factor (2^12 = 4096 rounds)
      The salt is randomly generated — same password hashes differently each time.

    Interview question: "Why does the same password produce a different hash each time?"
    Answer: bcrypt generates a random salt and embeds it in the hash output.
      The salt prevents rainbow table attacks and makes every hash unique.
    """
    if password_exceeds_bcrypt_limit(plain_password):
        raise ValueError("Password must be 72 bytes or less")
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a stored bcrypt hash.

    How it works internally:
      1. Extract the salt from the stored hash (it's embedded in the string)
      2. Hash the plain password with the same salt
      3. Compare the results — constant-time comparison to prevent timing attacks

    WHY constant-time comparison?
      A naive `hash1 == hash2` comparison short-circuits on the first different
      byte. An attacker could measure response times to guess bytes one by one.
      Constant-time comparison takes the same time regardless of where mismatch occurs.
    """
    if password_exceeds_bcrypt_limit(plain_password):
        return False
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT token operations ───────────────────────────────────────────────────────

def create_access_token(subject: str | Any) -> str:
    """
    Create a short-lived JWT access token.

    Args:
        subject: Typically the user's UUID (as string). This is the "sub" claim.

    WHY short expiry (30 min)?
      If an access token is stolen (XSS, MITM, logging error), the attacker
      has at most 30 minutes to use it. Short window = limited blast radius.

    JWT Claims used:
      sub (subject): who the token is about — the user's UUID
      exp (expiration): Unix timestamp when the token becomes invalid
      type: "access" — prevents a refresh token being used as an access token
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(subject),
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def create_refresh_token(subject: str | Any) -> str:
    """
    Create a long-lived JWT refresh token.

    WHY a separate refresh token and not just a longer-lived access token?
      1. Refresh tokens can be revoked server-side (store in Redis, delete on logout).
         Access tokens can't — they're stateless. But refresh tokens are used rarely
         (once every 30 min), so we CAN afford a Redis lookup for them.
      2. Refresh tokens should only travel to /auth/refresh — not to every endpoint.
         This limits their exposure.

    In production: store refresh token hash in Redis with the user's ID.
      On use: verify it exists in Redis. On logout: delete it from Redis.
      This is the "sliding session" pattern used by Google, GitHub, etc.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": str(subject),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_token(token: str) -> dict:
    """
    Decode and verify a JWT token.

    Raises JWTError if:
      - Signature is invalid (token was tampered with)
      - Token has expired (exp claim is in the past)
      - Token is malformed (not valid base64url-encoded JSON)

    WHY do we not need to query the DB to verify a JWT?
      The signature is computed with our SECRET_KEY.
      Only we can produce a valid signature — so if it verifies, we issued it.
      This is the key property that makes JWT stateless.
    """
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )
