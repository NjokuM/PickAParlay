import pytest
from jose import jwt

from backend import auth


def test_password_hashing(monkeypatch):
    monkeypatch.setattr(auth, "_HASH_ITERATIONS", 1000)
    h = auth.hash_password("hunter22")
    assert auth.verify_password("hunter22", h) and not auth.verify_password("wrong", h)
    assert not auth.verify_password("x", "no-dollar-sign") and not auth.verify_password("x", None)


def test_tokens_roundtrip():
    payload = auth.decode_token(auth.create_access_token(5, "jane", True))
    assert payload["sub"] == "5" and payload["is_admin"] is True


def test_register_first_user_is_admin_then_regular(api):
    first = api.post("/api/auth/register", json={"username": " Jane ", "password": "secret1", "invite_code": auth.INVITE_CODE})
    assert first.status_code == 200 and first.json()["is_admin"] is True and first.json()["username"] == "jane"
    second = api.post("/api/auth/register", json={"username": "bob", "password": "secret1", "invite_code": auth.INVITE_CODE})
    assert second.json()["is_admin"] is False


@pytest.mark.parametrize("body,code", [
    ({"username": "bob", "password": "secret1", "invite_code": "wrong"}, 403),
    ({"username": "bo", "password": "secret1", "invite_code": None}, 400),
    ({"username": "bobby", "password": "123", "invite_code": None}, 400),
])
def test_register_validation(api, body, code):
    body["invite_code"] = body["invite_code"] or auth.INVITE_CODE
    assert api.post("/api/auth/register", json=body).status_code == code


def test_duplicate_username(api, admin_headers):
    r = api.post("/api/auth/register", json={"username": "ADMIN", "password": "secret1", "invite_code": auth.INVITE_CODE})
    assert r.status_code == 409


def test_login_and_me(api, admin_headers):
    ok = api.post("/api/auth/login", json={"username": "admin", "password": "secret1"})
    assert ok.status_code == 200
    assert api.post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    me = api.get("/api/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["username"] == "admin"


def test_guards(api, admin_headers, user_headers):
    assert api.get("/api/auth/me").status_code == 401
    assert api.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    ghost = auth.create_access_token(999, "ghost", False)
    assert api.get("/api/auth/me", headers={"Authorization": f"Bearer {ghost}"}).status_code == 401
    # admin-only endpoint
    assert api.post("/api/refresh", headers=user_headers).status_code == 403


@pytest.mark.anyio
async def test_optional_user(fresh_db):
    assert await auth.optional_user(None) is None
    assert await auth.optional_user("garbage") is None
    uid = fresh_db.create_user("x", "h")
    assert (await auth.optional_user(auth.create_access_token(uid, "x", False)))["id"] == uid
