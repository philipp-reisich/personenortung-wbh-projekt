from api.auth import get_password_hash, verify_password, create_access_token


def test_password_hash_and_verify():
    password = "secret"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_create_access_token_contains_role_and_sub():
    token = create_access_token(subject="user1", role="admin", expires_delta=None)
    # Decode without verifying signature to inspect payload
    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    assert payload["sub"] == "user1"
    assert payload["role"] == "admin"