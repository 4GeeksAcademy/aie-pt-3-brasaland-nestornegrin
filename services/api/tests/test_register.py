"""POST /users — registro. Nace bajo la API de autenticación (crea la
cuenta y su contraseña hasheada), aunque vive en app/users/routes.py."""


def test_register_happy_path_creates_the_user_and_never_returns_the_password(client):
    response = client.post("/users", json={"email": "new@example.com", "password": "ValidPass123", "name": "New User"})

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_duplicate_email_returns_409(client, register_user):
    register_user(email="dup@example.com")

    response = client.post("/users", json={"email": "dup@example.com", "password": "OtherPass123", "name": "Other"})

    assert response.status_code == 409


def test_register_duplicate_email_check_is_case_insensitive(client, register_user):
    register_user(email="case@example.com")

    response = client.post("/users", json={"email": "CASE@EXAMPLE.COM", "password": "ValidPass123"})

    assert response.status_code == 409


def test_register_password_too_short_returns_400_identifying_the_field(client):
    response = client.post("/users", json={"email": "short@example.com", "password": "short", "name": "X"})

    assert response.status_code == 400
    body = response.json()
    assert any("password" in error.get("loc", []) for error in body["detail"])


def test_register_invalid_email_format_returns_400(client):
    response = client.post("/users", json={"email": "esto-no-es-un-email", "password": "ValidPass123"})

    assert response.status_code == 400
