"""Pruebas de la lógica de seguridad (hash, JWT, tokens de reseteo) a nivel
de función — sin pasar por ningún endpoint HTTP."""

from datetime import datetime, timedelta, timezone

import pytest
from jose import JWTError, jwt

from app.auth import security


class TestPasswordHashing:
    def test_hash_password_returns_a_different_string_than_the_plaintext(self):
        hashed = security.hash_password("SuperSecret123")
        assert hashed != "SuperSecret123"

    def test_verify_password_accepts_the_correct_password(self):
        hashed = security.hash_password("SuperSecret123")
        assert security.verify_password("SuperSecret123", hashed) is True

    def test_verify_password_rejects_a_wrong_password(self):
        hashed = security.hash_password("SuperSecret123")
        assert security.verify_password("OtraCosaTotalmenteDistinta", hashed) is False


class TestAccessTokens:
    def test_create_and_decode_round_trip_returns_the_same_user_id(self):
        token = security.create_access_token(42)
        assert security.decode_access_token(token) == 42

    def test_decode_rejects_a_tampered_token(self):
        token = security.create_access_token(1)
        # Cambia el último carácter de la firma para invalidarla sin tocar el formato.
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        with pytest.raises(JWTError):
            security.decode_access_token(tampered)

    def test_decode_rejects_an_expired_token(self):
        expired_payload = {"sub": "7", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}
        expired_token = jwt.encode(expired_payload, security.JWT_SECRET_KEY, algorithm=security.JWT_ALGORITHM)
        with pytest.raises(JWTError):
            security.decode_access_token(expired_token)

    def test_decode_rejects_a_token_whose_subject_is_not_numeric(self):
        bad_payload = {"sub": "no-soy-un-id", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
        bad_token = jwt.encode(bad_payload, security.JWT_SECRET_KEY, algorithm=security.JWT_ALGORITHM)
        with pytest.raises(JWTError):
            security.decode_access_token(bad_token)


class TestPasswordResetTokens:
    def test_generate_password_reset_token_is_different_each_call(self):
        assert security.generate_password_reset_token() != security.generate_password_reset_token()

    def test_hash_password_reset_token_is_deterministic(self):
        token = "el-mismo-token"
        assert security.hash_password_reset_token(token) == security.hash_password_reset_token(token)

    def test_hash_password_reset_token_differs_for_different_input(self):
        assert security.hash_password_reset_token("token-a") != security.hash_password_reset_token("token-b")
