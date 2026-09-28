from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import IntegrityError

from backend.app.database import SessionLocal, engine
from backend.app.models import User
from backend.app.news_models import (
    NewsDevice, NewsMedia, NewsNotification, NewsPoll, NewsPollOption, NewsPollVote, NewsPost, utcnow,
)
from backend.app.routers import news
from backend.app.services import news_polls
from backend.app.services.user_accounts import delete_user_account
from backend.app.utils.jwt import create_access_token


def run(coro):
    return asyncio.run(coro)


async def clear_news():
    async with SessionLocal() as session:
        for model in (NewsPollVote, NewsPollOption, NewsPoll, NewsNotification, NewsDevice, NewsMedia, NewsPost):
            await session.execute(delete(model))
        await session.commit()


async def account(*, admin=False, dispatcher=False, active=True):
    async with SessionLocal() as session:
        user = User(phone=f"+{str(uuid4().int)[:15]}", name="Private account identity",
                    is_admin=admin or dispatcher, is_active=active,
                    staff_role="dispatcher" if dispatcher else None)
        session.add(user)
        await session.commit()
        return user.id, {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest.fixture
def polls(client):
    run(clear_news())
    admin_id, admin = run(account(admin=True))
    resident_id, resident = run(account())
    other_id, other = run(account())
    yield client, admin, resident, other, admin_id, resident_id, other_id
    run(clear_news())


def publish(client, admin, *, text="", options=None, question="Что улучшить?", key=None):
    return client.post("/api/news", headers=admin, json={
        "text": text, "request_id": key or uuid4().hex,
        "poll": {"question": question, "options": options or ["Освещение", "Дороги"]},
    })


def cast(client, headers, post, option=0):
    return client.post(f"/api/news/{post['id']}/poll/vote", headers=headers,
                       json={"option_id": post["poll"]["options"][option]["id"]})


def read(client, headers, post):
    response = client.get(f"/api/news/{post['id']}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_poll_only_create_replay_and_single_notification(polls):
    client, admin, resident, _other, *_ = polls
    assert client.post("/api/news/devices", headers=resident,
                       json={"token": "poll-test-fcm-token"}).status_code == 204
    key = uuid4().hex
    first = publish(client, admin, key=key, question="  Что улучшить?  ", options=[" Свет ", "Дороги"])
    assert first.status_code == 201, first.text
    post = first.json()
    assert post["text"] == "" and post["poll"]["question"] == "Что улучшить?"
    assert [opt["text"] for opt in post["poll"]["options"]] == ["Свет", "Дороги"]
    assert post["poll"]["total_votes"] == 0 and post["poll"]["can_edit"]
    assert post["poll"]["my_option_id"] is None and not post["poll"]["is_closed"]
    replay = publish(client, admin, key=key, options=["Свет", "Дороги"])
    assert replay.status_code == 201 and replay.json() == post
    assert publish(client, admin, key=key, options=["Свет", "Парк"]).status_code == 409
    assert cast(client, resident, post).status_code == 200
    assert client.post(f"/api/news/{post['id']}/poll/close", headers=admin).status_code == 200

    async def counts():
        async with SessionLocal() as session:
            return [await session.scalar(select(func.count()).select_from(model))
                    for model in (NewsPost, NewsPoll, NewsPollOption, NewsNotification)]
    assert run(counts()) == [1, 1, 2, 1]


def test_historical_no_poll_fingerprint_and_old_client_replay(polls):
    client, admin, _resident, _other, admin_id, *_ = polls
    key = uuid4().hex
    payload = {"text": "Существующая новость", "media_ids": []}
    legacy_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    async def seed():
        async with SessionLocal() as session:
            post = NewsPost(author_id=admin_id, author_name="Председатель", request_id=key,
                            request_hash=legacy_hash, text=payload["text"])
            session.add(post)
            await session.commit()
            return post.id
    post_id = run(seed())
    for extra in ({}, {"poll": None}):
        response = client.post("/api/news", headers=admin, json={**payload, "request_id": key, **extra})
        assert response.status_code == 201 and response.json()["id"] == post_id
        assert response.json()["poll"] is None
    assert publish(client, admin, text=payload["text"], key=key).status_code == 409


def test_vote_replacement_idempotency_aggregates_and_privacy(polls):
    client, admin, resident, other, *_ = polls
    post = publish(client, admin).json()
    first_id, second_id = [item["id"] for item in post["poll"]["options"]]
    for _ in range(3):
        result = cast(client, resident, post).json()
        assert result["total_votes"] == 1 and result["my_option_id"] == first_id
    assert cast(client, other, post).json()["total_votes"] == 2
    changed = cast(client, resident, post, 1).json()
    assert changed["total_votes"] == 2 and changed["my_option_id"] == second_id
    assert [o["votes"] for o in changed["options"]] == [1, 1]
    assert not changed["can_edit"]
    assert read(client, admin, post)["poll"]["my_option_id"] is None
    assert read(client, other, post)["poll"]["my_option_id"] == first_id
    serialized = json.dumps(changed)
    assert not any(key in serialized for key in ("user_id", "login", "phone", "Private account identity", "voters"))
    assert read(client, resident, post)["version"] == 1
    another = publish(client, admin).json()
    invalid = client.post(f"/api/news/{another['id']}/poll/vote", headers=resident,
                          json={"option_id": first_id})
    assert invalid.status_code == 422


@pytest.mark.parametrize("poll", [
    {"question": " ", "options": ["A", "B"]},
    {"question": "x" * 301, "options": ["A", "B"]},
    {"question": "Q", "options": ["A"]},
    {"question": "Q", "options": [str(i) for i in range(11)]},
    {"question": "Q", "options": ["A", " "]},
    {"question": "Q", "options": ["A", "x" * 201]},
    {"question": "Q", "options": [" Дороги ", "дороги"]},
    {"question": "Q", "options": ["Детская  площадка", "Детская площадка"]},
])
def test_invalid_poll_definitions(polls, poll):
    client, admin, *_ = polls
    result = client.post("/api/news", headers=admin, json={"request_id": uuid4().hex, "poll": poll})
    assert result.status_code == 422
    assert client.get("/api/news", headers=admin).json()["items"] == []


def test_old_client_edit_preserves_votes_and_locked_definition_rolls_back(polls):
    client, admin, resident, *_ = polls
    post = publish(client, admin).json()
    cast(client, resident, post)
    changed = client.put(f"/api/news/{post['id']}", headers=admin, json={"text": "Уточнение", "version": 1})
    assert changed.status_code == 200
    saved = read(client, resident, post)
    assert saved["poll"]["total_votes"] == 1 and saved["poll"]["my_option_id"] is not None
    original_poll = saved["poll"]
    for definition in (None, {"question": "Другой вопрос", "options": ["A", "B"]}):
        denied = client.put(f"/api/news/{post['id']}", headers=admin,
                            json={"text": "Не сохранить", "version": 2, "poll": definition})
        assert denied.status_code == 409
        assert read(client, resident, post) == saved
    # A same-definition resend is safe and does not recreate option IDs.
    unchanged = client.put(f"/api/news/{post['id']}", headers=admin, json={
        "text": "Уточнение", "version": 2,
        "poll": {"question": original_poll["question"], "options": [o["text"] for o in original_poll["options"]]},
    })
    assert unchanged.status_code == 200
    assert read(client, resident, post)["poll"] == original_poll


def test_deleting_all_voters_does_not_unlock_started_poll(polls):
    client, admin, resident, other, _admin_id, resident_id, other_id = polls
    post = publish(client, admin).json()
    assert cast(client, resident, post).status_code == 200
    assert cast(client, other, post, 1).status_code == 200

    async def remove_accounts():
        async with SessionLocal() as session:
            for user_id in (resident_id, other_id):
                user = await session.get(User, user_id)
                await delete_user_account(session, user=user)
    run(remove_accounts())
    remaining = read(client, admin, post)
    assert remaining["poll"]["total_votes"] == 0
    assert remaining["poll"]["can_edit"] is False
    for definition in (None, {"question": "Переписанный вопрос", "options": ["A", "B"]}):
        changed = client.put(f"/api/news/{post['id']}", headers=admin, json={
            "version": 1, "text": "Текст", "poll": definition,
        })
        assert changed.status_code == 409
    text_edit = client.put(f"/api/news/{post['id']}", headers=admin,
                           json={"version": 1, "text": "Уточнение без изменения опроса"})
    assert text_edit.status_code == 200 and not text_edit.json()["poll"]["can_edit"]


def test_definition_edit_invalidates_stale_options_and_empty_removal_rolls_back(polls):
    client, admin, resident, *_ = polls
    post = publish(client, admin).json()
    changed = client.put(f"/api/news/{post['id']}", headers=admin, json={
        "version": 1, "poll": {"question": "Новый вопрос", "options": ["Освещение", "Дороги"]},
    })
    assert changed.status_code == 200
    assert cast(client, resident, post).status_code == 422
    current = changed.json()
    empty = client.put(f"/api/news/{post['id']}", headers=admin, json={"version": 2, "poll": None})
    assert empty.status_code == 422 and read(client, admin, post) == current
    kept = client.put(f"/api/news/{post['id']}", headers=admin, json={"version": 2})
    assert kept.status_code == 200 and kept.json()["poll"] == current["poll"]
    removed = client.put(f"/api/news/{post['id']}", headers=admin,
                         json={"version": 3, "text": "Только текст", "poll": None})
    assert removed.status_code == 200 and removed.json()["poll"] is None
    readded = client.put(f"/api/news/{post['id']}", headers=admin, json={
        "version": 4, "poll": {"question": "Ещё один", "options": ["A", "B"]},
    })
    assert readded.status_code == 200
    old_ids = {o["id"] for o in post["poll"]["options"] + current["poll"]["options"]}
    assert not old_ids.intersection(o["id"] for o in readded.json()["poll"]["options"])


def test_close_is_admin_only_idempotent_and_does_not_erase_results(polls):
    client, admin, resident, other, *_ = polls
    _dispatcher_id, dispatcher = run(account(dispatcher=True))
    post = publish(client, admin).json()
    assert publish(client, resident).status_code == 403
    assert publish(client, dispatcher).status_code == 403
    for denied in (resident, dispatcher):
        assert client.post(f"/api/news/{post['id']}/poll/close", headers=denied).status_code == 403
    assert client.post(f"/api/news/{post['id']}/poll/close").status_code == 401
    assert cast(client, resident, post).status_code == 200
    closed = client.post(f"/api/news/{post['id']}/poll/close", headers=admin)
    assert closed.status_code == 200
    assert closed.json()["is_closed"] and closed.json()["closed_at"] and not closed.json()["can_edit"]
    assert client.post(f"/api/news/{post['id']}/poll/close", headers=admin).json() == closed.json()
    assert cast(client, resident, post, 1).status_code == 409
    assert cast(client, other, post).status_code == 409
    assert read(client, resident, post)["poll"]["total_votes"] == 1
    changed = client.put(f"/api/news/{post['id']}", headers=admin, json={"version": 1, "text": "Итог"})
    assert changed.status_code == 200 and changed.json()["poll"]["is_closed"]


def test_deleted_missing_invalid_and_blocked_cannot_vote(polls):
    client, admin, resident, *_ = polls
    _blocked_id, blocked = run(account(active=False))
    post = publish(client, admin).json()
    assert client.post(f"/api/news/{post['id']}/poll/vote", json={"option_id": 1}).status_code == 401
    assert cast(client, blocked, post).status_code == 401
    for invalid in (0, -1, "1", 1.5):
        assert client.post(f"/api/news/{post['id']}/poll/vote", headers=resident,
                           json={"option_id": invalid}).status_code == 422
    assert client.delete(f"/api/news/{post['id']}?version=1", headers=admin).status_code == 204
    assert cast(client, resident, post).status_code == 404
    assert client.post(f"/api/news/{post['id']}/poll/close", headers=admin).status_code == 404
    plain = client.post("/api/news", headers=admin,
                        json={"request_id": uuid4().hex, "text": "Без опроса"}).json()
    assert client.post(f"/api/news/{plain['id']}/poll/vote", headers=resident,
                       json={"option_id": 1}).status_code == 404
    assert client.post(f"/api/news/{plain['id']}/poll/close", headers=admin).status_code == 404


def test_concurrent_vote_retries_and_replacement_leave_one_vote(polls):
    client, admin, resident, _other, _admin_id, resident_id, _other_id = polls
    post = publish(client, admin).json()
    barrier = Barrier(8)

    def worker(index):
        barrier.wait(timeout=10)
        return cast(client, resident, post, index % 2)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker, range(8)))
    assert [r.status_code for r in results] == [200] * 8
    assert all(r.json()["total_votes"] == 1 for r in results)

    async def stored():
        async with SessionLocal() as session:
            return list((await session.scalars(select(NewsPollVote).where(
                NewsPollVote.poll_id == post["id"], NewsPollVote.user_id == resident_id,
            ))).all())
    assert len(run(stored())) == 1
    assert read(client, resident, post)["poll"]["total_votes"] == 1


def test_concurrent_distinct_accounts_keep_all_votes(polls):
    client, admin, *_ = polls
    post = publish(client, admin).json()
    accounts = [run(account())[1] for _ in range(6)]
    barrier = Barrier(len(accounts))

    def worker(index):
        barrier.wait(timeout=10)
        return cast(client, accounts[index], post, index % 2)
    with ThreadPoolExecutor(max_workers=len(accounts)) as pool:
        results = list(pool.map(worker, range(len(accounts))))
    assert all(r.status_code == 200 for r in results)
    result = read(client, admin, post)["poll"]
    assert result["total_votes"] == 6 and [o["votes"] for o in result["options"]] == [3, 3]


def test_vote_waiting_on_close_or_delete_cannot_commit_after_it(polls):
    client, admin, _resident, _other, _admin_id, resident_id, _other_id = polls
    for deleted in (False, True):
        post = publish(client, admin).json()

        async def race():
            async with SessionLocal() as closing, SessionLocal() as voting:
                await news_polls.lock_active_post(closing, post["id"])
                if deleted:
                    await closing.execute(update(NewsPost).where(NewsPost.id == post["id"]).values(deleted_at=utcnow()))
                else:
                    await closing.execute(update(NewsPoll).where(NewsPoll.id == post["id"]).values(closed_at=utcnow()))
                waiting = asyncio.create_task(news_polls.vote(voting, post["id"], resident_id,
                                                             post["poll"]["options"][0]["id"]))
                await asyncio.sleep(0.05)
                assert not waiting.done(), "The vote must wait for the other database transaction"
                await closing.commit()
                with pytest.raises(HTTPException) as denied:
                    await waiting
                assert denied.value.status_code == (404 if deleted else 409)
            async with SessionLocal() as check:
                assert await check.scalar(select(func.count()).select_from(NewsPollVote).where(
                    NewsPollVote.poll_id == post["id"],
                )) == 0
        run(race())


@pytest.mark.parametrize("change", ["blocked", "deleted", "replaced"])
def test_previously_authenticated_vote_rechecks_account_after_waiting(polls, change):
    client, admin, _resident, _other, _admin_id, resident_id, _other_id = polls
    post = publish(client, admin).json()

    async def race():
        async with SessionLocal() as modifying, SessionLocal() as voting:
            # Hold the stale object just as get_current_user does before dispatch.
            authorized = await voting.get(User, resident_id)
            generation = authorized.auth_generation
            if change == "blocked":
                await modifying.execute(update(User).where(User.id == resident_id).values(is_active=False))
            else:
                await modifying.execute(delete(User).where(User.id == resident_id))
                if change == "replaced":
                    modifying.add(User(id=resident_id, phone=f"+{str(uuid4().int)[:15]}",
                                       auth_generation=uuid4().hex, is_active=True))
                    await modifying.flush()
            waiting = asyncio.create_task(news_polls.vote(voting, post["id"], resident_id,
                                                         post["poll"]["options"][0]["id"],
                                                         auth_generation=generation))
            await asyncio.sleep(0.05)
            assert not waiting.done()
            await modifying.commit()
            with pytest.raises(HTTPException) as denied:
                await waiting
            assert denied.value.status_code == 401
        async with SessionLocal() as check:
            assert await check.scalar(select(func.count()).select_from(NewsPollVote)) == 0
    run(race())


def test_previously_authorized_admin_cannot_close_after_demotion(polls):
    client, admin, _resident, _other, admin_id, *_ = polls
    post = publish(client, admin).json()

    async def race():
        async with SessionLocal() as modifying, SessionLocal() as closing:
            authorized = await closing.get(User, admin_id)
            generation = authorized.auth_generation
            await modifying.execute(update(User).where(User.id == admin_id).values(staff_role="dispatcher"))
            waiting = asyncio.create_task(news_polls.close(closing, post["id"], admin_id,
                                                          auth_generation=generation))
            await asyncio.sleep(0.05)
            assert not waiting.done()
            await modifying.commit()
            with pytest.raises(HTTPException) as denied:
                await waiting
            assert denied.value.status_code == 403
        async with SessionLocal() as check:
            assert (await check.get(NewsPoll, post["id"])).closed_at is None
    run(race())


@pytest.mark.parametrize("operation", ["register", "unregister"])
def test_stale_device_request_cannot_register_or_revoke_recycled_account(polls, operation):
    _client, _admin, _resident, _other, _admin_id, resident_id, _other_id = polls
    token = "synthetic-current-account-device-token"

    async def race():
        async with SessionLocal() as replacing, SessionLocal() as requesting:
            authorized = await requesting.get(User, resident_id)
            await replacing.execute(delete(User).where(User.id == resident_id))
            replacing.add(User(id=resident_id, phone=f"+{str(uuid4().int)[:15]}",
                               auth_generation=uuid4().hex, is_active=True))
            await replacing.flush()
            replacing.add(NewsDevice(user_id=resident_id, token=token, platform="android", active=True))
            await replacing.flush()
            body = news.DeviceBody(token=token)
            action = news.register_device if operation == "register" else news.unregister_device
            waiting = asyncio.create_task(action(body=body, session=requesting, user=authorized))
            await asyncio.sleep(0.05)
            assert not waiting.done()
            await replacing.commit()
            with pytest.raises(HTTPException) as denied:
                await waiting
            assert denied.value.status_code == 401
        async with SessionLocal() as check:
            devices = list((await check.scalars(select(NewsDevice).where(NewsDevice.user_id == resident_id))).all())
            assert len(devices) == 1 and devices[0].active and devices[0].token == token
    run(race())


def test_database_uniqueness_and_option_parent_constraint(polls):
    client, admin, resident, _other, _admin_id, resident_id, _other_id = polls
    first, second = publish(client, admin).json(), publish(client, admin).json()
    assert cast(client, resident, first).status_code == 200

    async def duplicate():
        async with SessionLocal() as session:
            session.add(NewsPollVote(poll_id=first["id"], user_id=resident_id,
                                     option_id=first["poll"]["options"][1]["id"]))
            with pytest.raises(IntegrityError):
                await session.commit()
    run(duplicate())
    # Verify the cross-poll constraint with enforcement enabled on an isolated
    # connection, without changing pooled connection settings for other suites.
    with sqlite3.connect(engine.url.database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            db.execute("INSERT INTO news_poll_votes (poll_id,user_id,option_id,updated_at) VALUES (?,?,?,?)",
                       (second["id"], resident_id, first["poll"]["options"][0]["id"], utcnow().isoformat()))


def test_archive_serializes_all_polls_in_constant_query_count(polls):
    client, admin, resident, *_ = polls
    posts = [publish(client, admin, question=f"Вопрос {index}").json() for index in range(7)]
    assert cast(client, resident, posts[-1]).status_code == 200
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT") and "news_poll" in statement:
            statements.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = client.get("/api/news?limit=20", headers=resident)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 7
    assert response.json()["items"][0]["poll"]["my_option_id"] is not None
    assert len(statements) == 2
