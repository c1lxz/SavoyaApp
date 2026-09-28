from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database import Base, SessionLocal
from backend.app.models import Request, User
from backend.app.news_models import NewsDevice, NewsMedia, NewsNotification, NewsPoll, NewsPollOption, NewsPollVote, NewsPost
from backend.app.routers.admin import admin_block_user, admin_update_staff_role
from backend.app.schemas import AdminUpdateStaffRolePayload
from backend.app.services.auth import ensure_admin_user
from backend.app.services.news_polls import serialize_polls
from backend.app.services.user_accounts import delete_user_account, ensure_users_schema
from backend.app.utils.jwt import create_access_token, decode_token


@pytest.fixture(autouse=True)
def initialized_app(client):
    """The shared test cleanup requires tables even for standalone migration tests."""
    return client


def test_staff_role_update_cors_preflight(client):
    from backend.app.main import settings
    origin = settings.cors_allow_origins[0]
    response = client.options('/api/admin/users/1/role', headers={
        'Origin': origin,
        'Access-Control-Request-Method': 'PATCH',
        'Access-Control-Request-Headers': 'authorization,content-type',
    })
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == origin
    assert 'PATCH' in response.headers['access-control-allow-methods'].split(', ')


def account(role: str | None = None, *, legacy: bool = False) -> tuple[int, dict[str, str]]:
    async def create():
        async with SessionLocal() as session:
            user = User(
                phone=f"+7999{str(uuid4().int)[-7:]}", login=f"role_{uuid4().hex[:12]}",
                name="Тестовый Сотрудник", is_admin=role is not None or legacy,
                staff_role=role, is_active=True,
            )
            session.add(user)
            await session.commit()
            return user.id
    user_id = asyncio.run(create())
    return user_id, {"Authorization": f"Bearer {create_access_token(subject=str(user_id))}"}


@pytest.mark.parametrize("role,legacy,expected", [
    (None, False, None), (None, True, "administration"),
    ("administration", False, "administration"), ("dispatcher", False, "dispatcher"),
])
def test_auth_payloads_expose_effective_role(client, role, legacy, expected):
    _, headers = account(role, legacy=legacy)
    response = client.get("/api/user/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["staff_role"] == expected
    assert response.json()["is_admin"] == (expected is not None)
    compat = client.get("/user/me", headers=headers)
    assert compat.status_code == 200
    assert compat.json()["staffRole"] == expected


def test_dispatcher_keeps_resident_management_and_monitor(client):
    _, dispatcher = account("dispatcher")
    resident_id, resident = account()
    for path in ("/api/admin/users", "/api/admin/requests", "/api/admin/monitor"):
        response = client.get(path, headers=dispatcher)
        assert response.status_code == 200, response.text
    residents = client.get("/api/admin/users", headers=dispatcher).json()["items"]
    assert all(not row["is_admin"] and row["staff_role"] is None for row in residents)

    async def create_pass():
        async with SessionLocal() as session:
            request = Request(resident_id=resident_id, key_type="Phone", key_value="+79990001122",
                              access_point_ids=[1], is_permanent=True, status="active")
            session.add(request)
            await session.commit()
            return request.id
    pass_id = asyncio.run(create_pass())
    assert client.delete(f"/api/admin/requests/{pass_id}", headers=dispatcher).status_code == 200
    assert client.post(f"/api/admin/users/{resident_id}/block", headers=dispatcher).status_code == 200
    assert client.get("/user/me", headers=resident).status_code == 401
    assert client.post(f"/api/admin/users/{resident_id}/unblock", headers=dispatcher).status_code == 200
    assert client.get("/user/me", headers=resident).status_code == 200
    assert client.delete(f"/api/admin/users/{resident_id}", headers=dispatcher).status_code == 200


def test_dispatcher_cannot_create_users_manage_staff_or_news(client):
    _, dispatcher = account("dispatcher")
    admin_id, _ = account("administration")
    for account_type in ("staff", "all"):
        assert client.get(f"/api/admin/users?account_type={account_type}", headers=dispatcher).status_code == 403
    for action in ("block", "unblock"):
        assert client.post(f"/api/admin/users/{admin_id}/{action}", headers=dispatcher).status_code == 403
    assert client.patch(f"/api/admin/users/{admin_id}/role", headers=dispatcher,
                        json={"staff_role": "dispatcher"}).status_code == 403
    for role in (None, "dispatcher", "administration"):
        response = client.post("/api/admin/users", headers=dispatcher, json={
            "full_name": "Новый Пользователь", "phone": "+79001234567", "plot_number": "12", "staff_role": role,
        })
        assert response.status_code == 403
    assert client.get("/api/news", headers=dispatcher).status_code == 200
    assert client.post("/api/news", headers=dispatcher, json={"text": "Forbidden", "request_id": uuid4().hex}).status_code == 403
    assert client.put("/api/news/999999", headers=dispatcher, json={"text": "Forbidden", "version": 1}).status_code == 403
    assert client.delete("/api/news/999999", headers=dispatcher).status_code == 403
    assert client.post("/api/news/media", headers=dispatcher, files={"file": ("a.txt", b"blocked", "text/plain")}).status_code == 403


def test_resident_and_unknown_roles_cannot_use_staff_api(client):
    for role in (None, "unknown"):
        _, headers = account(role)
        for path in ("/api/admin/users", "/api/admin/requests", "/api/admin/monitor"):
            assert client.get(path, headers=headers).status_code == 403


def test_administration_can_create_staff_without_gate_provisioning(client, monkeypatch):
    _, admin = account("administration")
    monkeypatch.setattr("backend.app.routers.admin.settings.gate_real_integration_enabled", True)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Creating staff must not provision resident Gate phone passes")

    monkeypatch.setattr("backend.app.routers.admin.link_existing_gate_passes_by_phone", forbidden)
    created = client.post("/api/admin/users", headers=admin, json={
        "full_name": "Иванов Диспетчер", "phone": f"+7911{str(uuid4().int)[-7:]}", "staff_role": "dispatcher",
    })
    assert created.status_code == 200, created.text
    user = created.json()
    assert user["is_admin"] is True
    assert user["staff_role"] == "dispatcher"
    assert user["plot_number"] is None and user["owner_index"] is None
    assert user["password"] and user["password_change_required"]
    login = client.post("/api/auth/login", json={"login": user["login"], "password": user["password"]})
    assert login.status_code == 200
    assert login.json()["user"]["staff_role"] == "dispatcher"
    assert login.json()["user"]["password_change_prompt_required"] is True
    compat = client.post("/auth/login", json={"login": user["login"], "password": user["password"]})
    assert compat.status_code == 200 and compat.json()["user"]["staffRole"] == "dispatcher"
    staff_list = client.get("/api/admin/users?account_type=staff", headers=admin).json()["items"]
    assert user["id"] in {item["id"] for item in staff_list}
    assert all(item["is_admin"] for item in staff_list)


def test_role_changes_revoke_existing_tokens_and_staff_block_is_immediate(client):
    _, admin = account("administration")
    staff_id, staff = account("administration")
    assert client.get("/api/admin/users?account_type=staff", headers=staff).status_code == 200
    changed = client.patch(f"/api/admin/users/{staff_id}/role", headers=admin, json={"staff_role": "dispatcher"})
    assert changed.status_code == 200
    assert changed.json()["staff_role"] == "dispatcher"
    assert client.get("/api/admin/users?account_type=staff", headers=staff).status_code == 403
    assert client.post("/api/news", headers=staff, json={"text": "Blocked", "request_id": uuid4().hex}).status_code == 403
    assert client.get("/api/admin/requests", headers=staff).status_code == 200
    assert client.get("/user/me", headers=staff).json()["staffRole"] == "dispatcher"
    assert client.post(f"/api/admin/users/{staff_id}/block", headers=admin).status_code == 200
    assert client.get("/api/admin/requests", headers=staff).status_code == 401
    assert client.post(f"/api/admin/users/{staff_id}/unblock", headers=admin).status_code == 200
    assert client.get("/api/admin/requests", headers=staff).status_code == 200


def test_admin_cannot_demote_block_or_delete_self_or_convert_resident(client):
    admin_id, admin = account("administration")
    resident_id, _ = account()
    assert client.patch(f"/api/admin/users/{admin_id}/role", headers=admin, json={"staff_role": "dispatcher"}).status_code == 409
    assert client.post(f"/api/admin/users/{admin_id}/block", headers=admin).status_code == 409
    assert client.delete(f"/api/admin/users/{admin_id}", headers=admin).status_code == 404
    assert client.patch(f"/api/admin/users/{resident_id}/role", headers=admin, json={"staff_role": "administration"}).status_code == 404
    assert client.patch(f"/api/admin/users/{admin_id}/role", headers=admin, json={"staff_role": "superuser"}).status_code == 422
    assert client.post("/api/admin/users", headers=admin, json={"full_name": "Новый Житель", "phone": "+79112223344"}).status_code == 422


def test_additive_migration_preserves_old_accounts_and_assigned_roles(tmp_path):
    async def check():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("""CREATE TABLE users (
                    id INTEGER PRIMARY KEY, phone VARCHAR(20) NOT NULL, name VARCHAR(100),
                    apartment VARCHAR(20), is_admin BOOLEAN NOT NULL, is_active BOOLEAN NOT NULL,
                    gate_user_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"""))
                await connection.execute(text("""INSERT INTO users (id, phone, name, apartment, is_admin, is_active, gate_user_id)
                    VALUES (1, '+79991111111', 'Old Admin', '1', 1, 1, 123),
                           (2, '+79992222222', 'Old Resident', '2', 0, 1, 456)"""))
            async with factory() as session:
                await ensure_users_schema(session)
                rows = list((await session.scalars(select(User).order_by(User.id))).all())
                assert [(u.id, u.phone, u.apartment, u.gate_user_id, u.staff_role) for u in rows] == [
                    (1, '+79991111111', '1', 123, 'administration'),
                    (2, '+79992222222', '2', 456, None),
                ]
                assert all(u.auth_generation is None for u in rows)
                rows[0].staff_role = "dispatcher"
                await session.commit()
                await ensure_users_schema(session)
                await session.refresh(rows[0])
                assert rows[0].staff_role == "dispatcher"
        finally:
            await engine.dispose()
    asyncio.run(check())


def test_bootstrap_preserves_existing_role_and_block_state(monkeypatch):
    login = f"bootstrap_role_{uuid4().hex[:12]}"
    phone = f"+7988{str(uuid4().int)[-7:]}"
    for key, value in {
        "bootstrap_admin_user": True, "admin_login": login, "admin_password": "local-test-password",
        "admin_phone": phone, "admin_full_name": "Тестовый Администратор", "admin_plot_number": "99",
    }.items():
        monkeypatch.setattr(f"backend.app.services.auth.settings.{key}", value)

    async def check():
        async with SessionLocal() as session:
            await ensure_admin_user(session)
            user = await session.scalar(select(User).where(User.login == login))
            assert user.is_active and user.staff_role == "administration"
            generation = user.auth_generation
            assert generation is not None and len(generation) == 32
            user.is_active = False
            user.staff_role = "dispatcher"
            await session.commit()
            await ensure_users_schema(session)
            await ensure_admin_user(session)
            await session.refresh(user)
            assert not user.is_active and user.staff_role == "dispatcher"
            assert user.auth_generation == generation
    asyncio.run(check())


def test_reused_user_id_rejects_old_jwt_even_in_same_second(client, monkeypatch):
    issued_at = datetime.now(timezone.utc).replace(microsecond=0)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return issued_at

    monkeypatch.setattr("backend.app.utils.jwt.datetime", FrozenDatetime)
    _, admin = account("administration")

    def create_and_login():
        created = client.post("/api/admin/users", headers=admin, json={
            "full_name": "Проверка Аккаунта", "phone": f"+7977{str(uuid4().int)[-7:]}", "plot_number": "101",
        })
        assert created.status_code == 200, created.text
        user = created.json()
        login = client.post("/api/auth/login", json={"login": user["login"], "password": user["password"]})
        assert login.status_code == 200, login.text
        return user["id"], login.json()["access_token"]

    old_id, old_token = create_and_login()
    old_headers = {"Authorization": f"Bearer {old_token}"}
    assert client.get("/user/me", headers=old_headers).status_code == 200
    assert client.delete(f"/api/admin/users/{old_id}", headers=admin).status_code == 200
    new_id, new_token = create_and_login()
    assert new_id == old_id
    old_claims, new_claims = decode_token(old_token), decode_token(new_token)
    assert old_claims["iat"] == new_claims["iat"]
    assert old_claims["auth_generation"] != new_claims["auth_generation"]
    assert client.get("/user/me", headers=old_headers).status_code == 401
    assert client.get("/user/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
    no_generation = create_access_token(str(new_id))
    assert client.get("/user/me", headers={"Authorization": f"Bearer {no_generation}"}).status_code == 401


def test_deleted_account_does_not_leave_votes_or_push_devices_with_sqlite_fk_off(tmp_path):
    async def check():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'deletion.db'}")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                assert await connection.scalar(text("PRAGMA foreign_keys")) == 0
            async with factory() as session:
                author = User(id=1, phone="+79000000001", is_admin=True, staff_role="administration")
                resident = User(id=2, phone="+79000000002", is_admin=False)
                session.add_all([author, resident])
                await session.flush()
                post = NewsPost(author_id=resident.id, author_name="Former Author", text="Poll", request_id="delete-poll", request_hash="test")
                session.add(post)
                await session.flush()
                poll = NewsPoll(id=post.id, question="Test question?")
                option = NewsPollOption(poll_id=post.id, position=0, text="Answer")
                devices = [NewsDevice(user_id=u.id, token=f"test-token-{u.id}", platform="android") for u in (author, resident)]
                media = NewsMedia(id="a" * 32, owner_id=resident.id, post_id=post.id, name="test.txt", mime_type="text/plain", kind="document", size_bytes=1)
                session.add_all([poll, option, media, *devices])
                await session.flush()
                session.add_all([
                    NewsPollVote(poll_id=post.id, user_id=resident.id, option_id=option.id),
                    NewsNotification(post_id=post.id, device_id=devices[0].id),
                    NewsNotification(post_id=post.id, device_id=devices[1].id),
                ])
                await session.commit()
                old_id = resident.id
                await delete_user_account(session, user=resident)
                replacement = User(phone="+79000000003", is_admin=False)
                session.add(replacement)
                await session.commit()
                assert replacement.id == old_id  # Exercise the legacy SQLite reuse.
                summary = (await serialize_polls(session, [post.id], replacement.id))[post.id]
                assert summary["my_option_id"] is None and summary["total_votes"] == 0
                assert await session.scalar(select(NewsDevice.id).where(NewsDevice.user_id == replacement.id)) is None
                notifications = list((await session.scalars(select(NewsNotification))).all())
                assert len(notifications) == 1 and notifications[0].device_id == devices[0].id
                await session.refresh(post)
                await session.refresh(media)
                assert post.author_id is None and media.owner_id is None
        finally:
            await engine.dispose()
    asyncio.run(check())


@pytest.mark.parametrize("actions", [("demote", "demote"), ("block", "block"), ("demote", "block")])
def test_concurrent_admin_mutations_keep_an_active_administrator(tmp_path, actions):
    async def check():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with factory() as session:
                session.add_all([User(id=i, phone=f"+7999000000{i}", is_admin=True,
                                     staff_role="administration", is_active=True) for i in (1, 2)])
                await session.commit()
            ready = asyncio.Event()
            loaded = 0

            async def mutate(actor_id, target_id, action):
                nonlocal loaded
                async with factory() as session:
                    actor = await session.get(User, actor_id)
                    # Both requests have already passed their dependency checks.
                    assert actor.effective_staff_role == "administration"
                    loaded += 1
                    if loaded == 2:
                        ready.set()
                    await ready.wait()
                    try:
                        if action == "demote":
                            await admin_update_staff_role(target_id, AdminUpdateStaffRolePayload(staff_role="dispatcher"), session, actor)
                        else:
                            await admin_block_user(target_id, session, actor)
                        return 200
                    except HTTPException as exc:
                        await session.rollback()
                        return exc.status_code
            outcomes = await asyncio.gather(mutate(1, 2, actions[0]), mutate(2, 1, actions[1]))
            assert sorted(outcomes) == [200, 403]
            async with factory() as session:
                rows = list((await session.scalars(select(User))).all())
                assert sum(u.is_active and u.effective_staff_role == "administration" for u in rows) == 1
        finally:
            await engine.dispose()
    asyncio.run(check())
