"""
tests/test_auth.py — Authentication tests (fixed for async mock patterns)
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.security import create_access_token, hash_password, verify_password


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        plain = "MyPassword1"
        assert hash_password(plain) != plain

    def test_hash_verifies_correctly(self):
        plain = "MyPassword1"
        assert verify_password(plain, hash_password(plain)) is True

    def test_wrong_password_fails(self):
        assert verify_password("WrongPassword1", hash_password("MyPassword1")) is False

    def test_same_password_different_hashes(self):
        """bcrypt random salt: same input → different hash, both verify."""
        plain = "MyPassword1"
        h1, h2 = hash_password(plain), hash_password(plain)
        assert h1 != h2
        assert verify_password(plain, h1) and verify_password(plain, h2)

    def test_hash_rejects_password_over_72_bytes(self):
        with pytest.raises(ValueError, match="72 bytes"):
            hash_password("A1" + "x" * 71)

    def test_verify_rejects_password_over_72_bytes_as_invalid(self):
        assert verify_password("A1" + "x" * 71, hash_password("SecurePass1")) is False

    def test_register_schema_counts_utf8_bytes(self):
        from pydantic import ValidationError
        from app.schemas.user import UserRegister

        with pytest.raises(ValidationError, match="72 bytes"):
            UserRegister(email="new@example.com", password="A1" + "\u00e9" * 36, full_name="Test")


class TestJWTTokens:
    def test_access_token_is_string(self):
        assert isinstance(create_access_token(str(uuid.uuid4())), str)

    def test_token_has_three_parts(self):
        token = create_access_token(str(uuid.uuid4()))
        assert len(token.split(".")) == 3

    def test_decode_returns_correct_subject(self):
        from app.core.security import decode_token
        uid = str(uuid.uuid4())
        payload = decode_token(create_access_token(uid))
        assert payload["sub"] == uid
        assert payload["type"] == "access"

    def test_tampered_token_fails(self):
        """Flipping a byte in the signature must cause verification to fail."""
        from jose import JWTError
        from app.core.security import decode_token

        token = create_access_token(str(uuid.uuid4()))
        header, payload_b64, sig = token.split(".")
        # Corrupt the signature by reversing it — guaranteed to differ
        corrupted = f"{header}.{payload_b64}.{sig[::-1]}"
        with pytest.raises(JWTError):
            decode_token(corrupted)

    def test_expired_token_fails(self):
        from datetime import datetime, timedelta, timezone
        from jose import JWTError, jwt
        from app.core.config import settings
        from app.core.security import decode_token

        expired = jwt.encode(
            {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) - timedelta(seconds=1), "type": "access"},
            settings.SECRET_KEY, algorithm=settings.ALGORITHM
        )
        with pytest.raises(JWTError):
            decode_token(expired)


class TestAuthService:
    """
    WHY these mock patterns?
      db.execute() is async → must be AsyncMock
      .scalar_one_or_none() is sync (called on the result) → MagicMock
      db.get() is async → AsyncMock

    Common mistake: making scalar_one_or_none an AsyncMock causes
    'coroutine object has no attribute hashed_password' — exactly what we saw.
    The fix: execute is async, but its return value's methods are sync.
    """

    @pytest.fixture
    def mock_db_no_user(self):
        """DB that returns None for all queries — user not found."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock
        db.get = AsyncMock(return_value=None)
        db.flush = AsyncMock()
        return db

    @pytest.fixture
    def mock_db_with_user(self):
        """DB that returns a fake active user."""
        from app.models.user import User

        fake_user = MagicMock(spec=User)
        fake_user.hashed_password = hash_password("CorrectPassword1")
        fake_user.is_active = True
        fake_user.id = uuid.uuid4()

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = fake_user
        db.execute.return_value = result_mock
        db.get = AsyncMock(return_value=fake_user)
        db.flush = AsyncMock()
        return db, fake_user

    @pytest.mark.asyncio
    async def test_register_hashes_password(self):
        """Register with explicit None result — no existing user."""
        from app.schemas.user import UserRegister
        from app.services.auth_service import AuthService

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None  # email not taken
        db.execute.return_value = result_mock
        db.flush = AsyncMock()

        user = await AuthService(db).register(
            UserRegister(email="new@example.com", password="SecurePass1", full_name="Test")
        )
        assert user.hashed_password != "SecurePass1"
        assert verify_password("SecurePass1", user.hashed_password)

    @pytest.mark.asyncio
    async def test_register_duplicate_email_raises_409(self, mock_db_with_user):
        from fastapi import HTTPException
        from app.schemas.user import UserRegister
        from app.services.auth_service import AuthService

        db, _ = mock_db_with_user
        with pytest.raises(HTTPException) as exc:
            await AuthService(db).register(
                UserRegister(email="taken@example.com", password="SecurePass1", full_name="X")
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_login_wrong_password_raises_401(self, mock_db_with_user):
        from fastapi import HTTPException
        from app.services.auth_service import AuthService

        db, _ = mock_db_with_user
        with pytest.raises(HTTPException) as exc:
            await AuthService(db).login("user@example.com", "WrongPassword1")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_login_correct_password_returns_tokens(self, mock_db_with_user):
        from app.services.auth_service import AuthService

        db, _ = mock_db_with_user
        result = await AuthService(db).login("user@example.com", "CorrectPassword1")
        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"

    @pytest.mark.asyncio
    async def test_login_nonexistent_user_same_error_as_wrong_password(self, mock_db_no_user):
        """User enumeration prevention: same 401 message for both failure modes."""
        from fastapi import HTTPException
        from app.services.auth_service import AuthService

        with pytest.raises(HTTPException) as exc:
            await AuthService(mock_db_no_user).login("nobody@example.com", "AnyPassword1")
        assert exc.value.status_code == 401
        assert "Invalid email or password" in exc.value.detail
