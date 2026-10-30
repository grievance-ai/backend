"""Integration tests for the admin API: users, permissions, activities."""

from httpx import AsyncClient

from tests.conftest import LoginAs, MakeUser

ADMIN = "/api/v2/xuanwu/admin"


def _csrf(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


# --- users -------------------------------------------------------------------
async def test_list_and_filter_users(
    client: AsyncClient, login_as: LoginAs, make_user: MakeUser
) -> None:
    await login_as(role="admin")
    target = (await make_user(role="member")).uid

    resp = await client.get(f"{ADMIN}/users", params={"uid": target})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["uid"] == target
    assert body["page"] == 1 and body["limit"] == 25


async def test_get_user_includes_labels(
    client: AsyncClient, login_as: LoginAs, make_user: MakeUser
) -> None:
    _, csrf = await login_as(role="admin")
    target = (await make_user(role="member")).uid
    await client.post(
        f"{ADMIN}/users/{target}/labels",
        json={"key": "email", "value": "verified", "scope": "private"},
        headers=_csrf(csrf),
    )
    resp = await client.get(f"{ADMIN}/users/{target}")
    keys = {label["key"] for label in resp.json()["data"]["labels"]}
    assert "email" in keys


async def test_admin_label_drives_level_to_three(
    client: AsyncClient, login_as: LoginAs, make_user: MakeUser
) -> None:
    _, csrf = await login_as(role="admin")
    target = (await make_user(role="member")).uid

    last = None
    for key in ("email", "phone", "document"):
        last = await client.post(
            f"{ADMIN}/users/{target}/labels",
            json={"key": key, "value": "verified", "scope": "private"},
            headers=_csrf(csrf),
        )
    assert last is not None
    body = last.json()["data"]
    assert body["level"] == 3  # email+phone+document verified by an admin
    assert body["state"] == "active"


async def test_set_state_and_role(
    client: AsyncClient, login_as: LoginAs, make_user: MakeUser
) -> None:
    _, csrf = await login_as(role="admin")
    target = (await make_user(role="member")).uid

    banned = await client.put(
        f"{ADMIN}/users/{target}/state", json={"state": "banned"}, headers=_csrf(csrf)
    )
    assert banned.json()["data"]["state"] == "banned"

    promoted = await client.put(
        f"{ADMIN}/users/{target}/role", json={"role": "staff"}, headers=_csrf(csrf)
    )
    assert promoted.json()["data"]["role"] == "staff"

    no_change = await client.put(
        f"{ADMIN}/users/{target}/role", json={"role": "staff"}, headers=_csrf(csrf)
    )
    assert no_change.status_code == 422
    assert "admin.user.role_no_change" in no_change.json()["errors"]


# --- permissions (superadmin only) -------------------------------------------
async def test_permissions_crud(client: AsyncClient, login_as: LoginAs) -> None:
    _, csrf = await login_as(role="superadmin")

    created = await client.post(
        f"{ADMIN}/permissions",
        json={
            "role": "manager",
            "verb": "get",
            "path": "/api/v2/xuanwu/admin/",
            "action": "accept",
        },
        headers=_csrf(csrf),
    )
    assert created.status_code == 200
    perm = created.json()["data"]
    assert perm["verb"] == "GET" and perm["action"] == "ACCEPT"  # normalized

    listed = await client.get(f"{ADMIN}/permissions")
    assert any(p["id"] == perm["id"] for p in listed.json()["data"]["items"])

    updated = await client.put(
        f"{ADMIN}/permissions/{perm['id']}", json={"action": "drop"}, headers=_csrf(csrf)
    )
    assert updated.json()["data"]["action"] == "DROP"

    deleted = await client.request(
        "DELETE", f"{ADMIN}/permissions/{perm['id']}", headers=_csrf(csrf)
    )
    assert deleted.status_code == 200


async def test_invalid_verb_rejected(client: AsyncClient, login_as: LoginAs) -> None:
    _, csrf = await login_as(role="superadmin")
    resp = await client.post(
        f"{ADMIN}/permissions",
        json={"role": "manager", "verb": "FETCH", "path": "/x/", "action": "accept"},
        headers=_csrf(csrf),
    )
    assert resp.status_code == 422
    assert "admin.permissions.invalid_verb" in resp.json()["errors"]


async def test_plain_admin_cannot_manage_permissions(
    client: AsyncClient, login_as: LoginAs
) -> None:
    await login_as(role="admin")
    resp = await client.get(f"{ADMIN}/permissions")
    assert resp.status_code == 403
    assert "authz.forbidden" in resp.json()["errors"]


# --- activities --------------------------------------------------------------
async def test_activities_are_listed_and_filterable(client: AsyncClient, login_as: LoginAs) -> None:
    # Logging in as admin writes a `session`/`login` activity.
    await login_as(role="admin")
    resp = await client.get(f"{ADMIN}/activities", params={"topic": "session", "action": "login"})
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert items and all(a["topic"] == "session" for a in items)


# --- authz -------------------------------------------------------------------
async def test_member_forbidden_on_admin_users(client: AsyncClient, login_as: LoginAs) -> None:
    await login_as(role="member")
    resp = await client.get(f"{ADMIN}/users")
    assert resp.status_code == 403
