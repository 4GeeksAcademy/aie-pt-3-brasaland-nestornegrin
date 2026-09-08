"""POST /auth/login."""


def test_login_happy_path_returns_an_access_token(client, register_user):
    register_user(email="login@example.com", password="ValidPass123")

    response = client.post("/auth/login", json={"email": "login@example.com", "password": "ValidPass123"})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_login_email_is_case_insensitive(client, register_user):
    register_user(email="mixed@example.com", password="ValidPass123")

    response = client.post("/auth/login", json={"email": "MIXED@Example.COM", "password": "ValidPass123"})

    assert response.status_code == 200


def test_login_accepts_username_field_as_an_alias_for_email(client, register_user):
    register_user(email="alias@example.com", password="ValidPass123")

    response = client.post("/auth/login", json={"username": "alias@example.com", "password": "ValidPass123"})

    assert response.status_code == 200


def test_login_wrong_password_returns_401(client, register_user):
    register_user(email="wrongpass@example.com", password="ValidPass123")

    response = client.post("/auth/login", json={"email": "wrongpass@example.com", "password": "Incorrecta1"})

    assert response.status_code == 401


def test_login_nonexistent_email_returns_401(client):
    response = client.post("/auth/login", json={"email": "nadie@example.com", "password": "ValidPass123"})

    assert response.status_code == 401


def test_login_wrong_password_and_nonexistent_user_give_the_identical_error(client, register_user):
    """No debe poder distinguirse, por el mensaje, si el email existe o no."""
    register_user(email="exists@example.com", password="ValidPass123")

    wrong_password = client.post("/auth/login", json={"email": "exists@example.com", "password": "Mala1234"})
    no_such_user = client.post("/auth/login", json={"email": "noexiste@example.com", "password": "Mala1234"})

    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json()["detail"] == no_such_user.json()["detail"]
