"""POST /auth/change-password."""


def test_change_password_happy_path_changes_the_password(client, register_user, auth_headers):
    register_user(email="change@example.com", password="OldPass123")
    headers = auth_headers(email="change@example.com", password="OldPass123", register=False)

    response = client.post(
        "/auth/change-password",
        json={"current_password": "OldPass123", "new_password": "NewPass456"},
        headers=headers,
    )

    assert response.status_code == 200
    new_login = client.post("/auth/login", json={"email": "change@example.com", "password": "NewPass456"})
    assert new_login.status_code == 200


def test_change_password_wrong_current_password_returns_400(client, register_user, auth_headers):
    register_user(email="wrongcurrent@example.com", password="OldPass123")
    headers = auth_headers(email="wrongcurrent@example.com", password="OldPass123", register=False)

    response = client.post(
        "/auth/change-password",
        json={"current_password": "Incorrecta1", "new_password": "NewPass456"},
        headers=headers,
    )

    assert response.status_code == 400


def test_change_password_without_a_token_returns_401(client):
    response = client.post(
        "/auth/change-password",
        json={"current_password": "x", "new_password": "NewPass456"},
    )

    assert response.status_code == 401


def test_change_password_new_password_too_short_returns_400(client, register_user, auth_headers):
    register_user(email="shortnew@example.com", password="OldPass123")
    headers = auth_headers(email="shortnew@example.com", password="OldPass123", register=False)

    response = client.post(
        "/auth/change-password",
        json={"current_password": "OldPass123", "new_password": "short"},
        headers=headers,
    )

    assert response.status_code == 400
