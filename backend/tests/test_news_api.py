from __future__ import annotations

import asyncio
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from sqlalchemy import delete, select, update

from backend.app.database import SessionLocal
from backend.app.models import User
from backend.app.news_models import NewsDevice, NewsMedia, NewsNotification, NewsPost, utcnow
from backend.app.routers import news
from backend.app.services import news_media
from backend.app.services import news_notifications
from backend.app.services.news_notifications import PushFailure, process_outbox_once
from backend.app.utils.jwt import create_access_token, decode_token


def run(coro):
    return asyncio.run(coro)


async def reset_news():
    async with SessionLocal() as session:
        for model in (NewsNotification, NewsDevice, NewsMedia, NewsPost):
            await session.execute(delete(model))
        await session.commit()


async def create_user(admin=False):
    async with SessionLocal() as session:
        user = User(phone=f"+{str(uuid4().int)[:15]}", name="Председатель" if admin else "Житель", is_admin=admin, is_active=True)
        session.add(user)
        await session.commit()
        return user.id


@pytest.fixture
def setup(client, tmp_path, monkeypatch):
    run(reset_news())
    monkeypatch.setattr(news.settings, "news_media_dir", str(tmp_path / "media"))
    admin_id, resident_id, other_id = run(create_user(True)), run(create_user()), run(create_user(True))
    headers = lambda value: {"Authorization": f"Bearer {create_access_token(str(value))}"}
    yield client, headers(admin_id), headers(resident_id), headers(other_id)
    run(reset_news())


def publish(client, admin, text="Новость посёлка", ids=None, key=None):
    return client.post("/api/news", headers=admin, json={"text": text, "media_ids": ids or [], "request_id": key or uuid4().hex})


def upload(client, admin, name="план.pdf", data=b"%PDF-1.7\ncontent", mime="application/pdf"):
    return client.post("/api/news/media", headers=admin, files={"file": (name, data, mime)})


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (1600, 1200), "green").save(buffer, "PNG")
    return buffer.getvalue()


def test_permissions_and_blocked_accounts(setup):
    client, admin, resident, _other = setup
    assert client.get("/api/news").status_code == 401
    assert publish(client, resident).status_code == 403
    assert upload(client, resident).status_code == 403
    post = publish(client, admin).json()
    assert client.get(f"/api/news/{post['id']}", headers=resident).status_code == 200
    assert client.put(f"/api/news/{post['id']}", headers=resident, json={"text": "Взлом", "version": 1}).status_code == 403
    assert client.delete(f"/api/news/{post['id']}?version=1", headers=resident).status_code == 403
    async def block():
        user_id = int(decode_token(resident["Authorization"].split(" ")[1])["sub"])
        async with SessionLocal() as session:
            await session.execute(update(User).where(User.id == user_id).values(is_active=False))
            await session.commit()
    run(block())
    assert client.get("/api/news", headers=resident).status_code == 401


def test_latest_archive_and_optimistic_edit_delete(setup):
    client, admin, resident, _other = setup
    posts = [publish(client, admin, text=f"Новость {i}").json() for i in range(4)]
    latest = client.get("/api/news", headers=resident).json()
    assert [p["id"] for p in latest["items"]] == [posts[-1]["id"]]
    # A newer publication does not shift or duplicate the cursor-based archive.
    publish(client, admin, text="Ещё новее")
    archive = client.get(f"/api/news?limit=2&before_id={latest['next_cursor']}", headers=resident).json()
    assert [p["id"] for p in archive["items"]] == [posts[2]["id"], posts[1]["id"]]
    end = client.get(f"/api/news?before_id={archive['next_cursor']}", headers=resident).json()
    assert end["items"][0]["id"] == posts[0]["id"] and end["next_cursor"] is None
    post_id = posts[-1]["id"]
    edited = client.put(f"/api/news/{post_id}", headers=admin, json={"text": "Исправлено", "media_ids": [], "version": 1})
    assert edited.status_code == 200 and edited.json()["version"] == 2 and edited.json()["updated_at"]
    assert client.put(f"/api/news/{post_id}", headers=admin, json={"text": "Устарело", "version": 1}).status_code == 409
    assert client.delete(f"/api/news/{post_id}?version=1", headers=admin).status_code == 409
    assert client.delete(f"/api/news/{post_id}?version=2", headers=admin).status_code == 204
    assert client.get(f"/api/news/{post_id}", headers=resident).status_code == 404


async def notifications():
    async with SessionLocal() as session:
        return list((await session.scalars(select(NewsNotification))).all())


def test_idempotency_and_single_publish_notification(setup):
    client, admin, resident, _other = setup
    assert client.post("/api/news/devices", headers=resident, json={"token": "resident-fcm-token-1"}).status_code == 204
    key = uuid4().hex
    first, second = publish(client, admin, key=key), publish(client, admin, key=key)
    assert first.status_code == second.status_code == 201 and first.json()["id"] == second.json()["id"]
    assert publish(client, admin, "Другое содержание", key=key).status_code == 409
    assert len(run(notifications())) == 1
    post_id = first.json()["id"]
    client.put(f"/api/news/{post_id}", headers=admin, json={"text": "Исправленный текст", "version": 1})
    assert len(run(notifications())) == 1
    client.delete(f"/api/news/{post_id}?version=2", headers=admin)
    assert publish(client, admin, key=key).status_code == 410
    assert run(notifications())[0].status == "cancelled"


def test_images_thumbnails_signed_urls_and_range(setup):
    client, admin, resident, _other = setup
    image = upload(client, admin, "Фото.png", png_bytes(), "image/png")
    assert image.status_code == 201
    item = image.json()
    assert item["kind"] == "image" and item["thumbnail_url"]
    post = publish(client, admin, ids=[item["id"]]).json()
    assert post["media"][0]["name"] == "Фото.png"
    # Signed URL supports native players which cannot attach a bearer header.
    response = client.get(item["url"])
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    thumbnail = client.get(item["thumbnail_url"])
    with Image.open(io.BytesIO(thumbnail.content)) as decoded:
        assert max(decoded.size) <= 1200
    part = client.get(item["url"], headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and part.content == response.content[:10]
    assert part.headers["content-range"].startswith("bytes 0-9/")
    assert client.head(item["url"]).headers["content-length"] == str(len(response.content))
    assert client.get(item["url"], headers={"Range": "bytes=-8"}).content == response.content[-8:]
    assert client.get(item["url"], headers={"Range": "bytes=999999999-"}).status_code == 416
    assert client.get(item["url"].replace("signature=", "signature=broken")).status_code in (403, 422)
    assert client.get(item["url"].split("?")[0]).status_code == 422
    client.delete(f"/api/news/{post['id']}?version=1", headers=admin)
    assert client.get(item["url"]).status_code == 404


def test_upload_size_image_validation_documents_and_ownership(setup, monkeypatch):
    client, admin, resident, other = setup
    monkeypatch.setattr(news.settings, "news_max_upload_bytes", 2048)
    assert upload(client, admin, data=b"x" * 2049).status_code == 413
    assert upload(client, admin, data=b"x" * 80000).status_code == 413
    assert upload(client, admin, data=b"").status_code == 422
    assert upload(client, admin, "bad.jpg", b"<script>bad</script>", "image/jpeg").status_code == 422
    active = upload(client, admin, "../../evil.html", b"<script>alert(1)</script>", "text/html").json()
    assert active["name"] == "evil.html" and active["kind"] == "document"
    fetched = client.get(active["url"])
    assert fetched.headers["content-type"] == "application/octet-stream"
    assert fetched.headers["content-disposition"].startswith("attachment;")
    assert "sandbox" in fetched.headers["content-security-policy"]
    assert publish(client, other, ids=[active["id"]]).status_code == 409
    post = publish(client, admin, ids=[active["id"]]).json()
    assert publish(client, admin, ids=[active["id"]]).status_code == 409
    assert client.delete(f"/api/news/media/{active['id']}", headers=admin).status_code == 404
    assert client.get("/api/news", headers=resident).json()["items"][0]["id"] == post["id"]


def test_media_removal_and_unattached_cleanup(setup):
    client, admin, _resident, _other = setup
    detached = upload(client, admin).json()
    kept = upload(client, admin).json()
    post = publish(client, admin, ids=[kept["id"]]).json()

    async def age_and_clean():
        async with SessionLocal() as session:
            await session.execute(update(NewsMedia).values(detached_at=utcnow() - timedelta(days=2)))
            await session.commit()
            return await news_media.cleanup_unattached(session)

    assert run(age_and_clean()) == 1
    assert client.get(detached["url"]).status_code == 404
    assert client.get(kept["url"]).status_code == 200
    response = client.put(f"/api/news/{post['id']}", headers=admin, json={"text": "Без файла", "version": 1})
    assert response.status_code == 200 and response.json()["media"] == []
    assert client.get(kept["url"]).status_code == 404


class FakeSender:
    def __init__(self, configured=True, failure=None):
        self.configured, self.failure, self.calls = configured, failure, []

    async def send(self, token, post):
        self.calls.append((token, post.id))
        if self.failure:
            raise self.failure


def test_outbox_missing_config_acceptance_retry_and_expired_token(setup):
    client, admin, resident, _other = setup
    client.post("/api/news/devices", headers=resident, json={"token": "outbox-device-1"})
    publish(client, admin)
    assert run(process_outbox_once(FakeSender(configured=False))) == 0
    assert run(notifications())[0].status == "pending"
    sender = FakeSender(failure=PushFailure("fcm_transport_unknown"))
    assert run(process_outbox_once(sender)) == 1
    first = run(notifications())[0]
    assert first.status == "retry" and first.attempts == 1 and first.sent_at is None

    async def make_due():
        async with SessionLocal() as session:
            await session.execute(update(NewsNotification).values(next_attempt_at=utcnow() - timedelta(seconds=1)))
            await session.commit()

    run(make_due())
    sender = FakeSender()
    assert run(process_outbox_once(sender)) == 1
    assert run(process_outbox_once(sender)) == 0
    assert len(sender.calls) == 1 and run(notifications())[0].status == "sent"
    publish(client, admin)
    assert run(process_outbox_once(FakeSender(failure=PushFailure("fcm_unregistered", invalid_token=True, permanent=True)))) == 1
    assert run(notifications())[-1].status == "failed"
    publish(client, admin)
    assert len(run(notifications())) == 2  # Invalid registration does not receive future jobs.


def test_logout_cancel_and_stale_registration(setup):
    client, admin, resident, _other = setup
    token = "logout-device-token"
    client.post("/api/news/devices", headers=resident, json={"token": token})
    publish(client, admin)
    assert client.request("DELETE", "/api/news/devices", headers=resident, json={"token": token}).status_code == 204
    assert run(notifications())[0].status == "cancelled"
    client.post("/api/news/devices", headers=resident, json={"token": token})

    async def stale():
        async with SessionLocal() as session:
            await session.execute(update(NewsDevice).values(updated_at=utcnow() - timedelta(days=31)))
            await session.commit()

    run(stale())
    publish(client, admin)
    assert len(run(notifications())) == 1


def test_expired_signature(setup):
    client, admin, _resident, _other = setup
    media = upload(client, admin).json()
    expires = int(time.time()) - 1
    signature = news_media._signature(media["id"], "content", expires)
    assert client.get(f"/api/news/media/{media['id']}/content?expires={expires}&signature={signature}").status_code == 403


def test_chunked_body_limit_and_draft_discard(setup, monkeypatch):
    client, admin, _resident, other = setup
    monkeypatch.setattr(news.settings, "news_max_upload_bytes", 1024)
    boundary = "news-test-boundary"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="large.bin"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode() + b"x" * 70000 + f"\r\n--{boundary}--\r\n".encode()
    response = client.post("/api/news/media", headers={**admin, "Content-Type": f"multipart/form-data; boundary={boundary}"},
                           content=(body[i:i+8192] for i in range(0, len(body), 8192)))
    assert response.status_code == 413
    assert not list(news_media.media_path("0" * 32).parent.glob("*.blob"))
    attachment = upload(client, admin).json()
    assert client.delete(f"/api/news/media/{attachment['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/news/media/{attachment['id']}", headers=admin).status_code == 204
    assert client.get(attachment["url"]).status_code == 404


def test_concurrent_publication_idempotency_and_worker_leases(setup):
    client, admin, resident, _other = setup
    client.post("/api/news/devices", headers=resident, json={"token": "concurrent-device"})
    key = uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: publish(client, admin, key=key), range(2)))
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert len(run(notifications())) == 1

    async def concurrent_workers():
        sender = FakeSender()
        results = await asyncio.gather(process_outbox_once(sender), process_outbox_once(sender))
        return results, sender.calls

    results, calls = run(concurrent_workers())
    assert sum(results) == 1 and len(calls) == 1


def test_device_token_ascii_and_index_byte_boundaries(setup):
    client, _admin, resident, _other = setup
    for token in ("x" * 2049, "я" * 20, "token with spaces", "short"):
        assert client.post("/api/news/devices", headers=resident, json={"token": token}).status_code == 422
    assert client.post("/api/news/devices", headers=resident, json={"token": "a" * 2048}).status_code == 204
    assert client.post("/api/news/devices", headers=resident, json={"token": "FCM:valid_token-123"}).status_code == 204


def test_saved_draft_media_refresh_permissions_and_expiry(setup, monkeypatch):
    client, admin, resident, other = setup
    media = upload(client, admin).json()
    route = f"/api/news/media/{media['id']}"
    assert client.get(route, headers=admin).json()["id"] == media["id"]
    assert client.get(route, headers=resident).status_code == 403
    assert client.get(route, headers=other).status_code == 404

    async def expire():
        async with SessionLocal() as session:
            await session.execute(update(NewsMedia).where(NewsMedia.id == media["id"]).values(detached_at=utcnow() - timedelta(days=2)))
            await session.commit()

    run(expire())
    assert client.get(route, headers=admin).status_code == 404
    assert publish(client, admin, ids=[media["id"]]).status_code == 409
    monkeypatch.setattr(news.settings, "news_max_unattached_uploads", 1)
    live_media = upload(client, admin).json()
    assert upload(client, admin).status_code == 429
    post = publish(client, admin, ids=[live_media["id"]]).json()
    live_route = f"/api/news/media/{live_media['id']}"
    assert client.get(live_route, headers=other).status_code == 200
    client.delete(f"/api/news/{post['id']}?version=1", headers=admin)
    assert client.get(live_route, headers=admin).status_code == 404
    assert upload(client, admin).status_code == 201  # Deleted post media must not consume draft quota.


def test_post_content_limits_and_media_only_publication(setup):
    client, admin, resident, _other = setup
    assert publish(client, admin, text=" \n\t").status_code == 422
    assert publish(client, admin, text="x" * 20001).status_code == 422
    assert publish(client, admin, text="x" * 20000).status_code == 201
    media = [upload(client, admin, name=f"{i}.txt", data=str(i).encode()).json() for i in range(11)]
    ids = [item["id"] for item in media]
    assert publish(client, admin, text="", ids=ids).status_code == 422
    assert publish(client, admin, ids=[ids[0], ids[0]]).status_code == 422
    assert publish(client, admin, ids=["../file"]).status_code == 422
    result = publish(client, admin, text="", ids=ids[:10])
    assert result.status_code == 201
    post = client.get(f"/api/news/{result.json()['id']}", headers=resident).json()
    assert post["text"] == "" and [item["id"] for item in post["media"]] == ids[:10]
    assert client.get("/api/news?limit=21", headers=resident).status_code == 422
    assert client.get("/api/news?before_id=0", headers=resident).status_code == 422


def test_failed_publication_and_edit_roll_back_all_changes(setup):
    client, admin, resident, other = setup
    client.post("/api/news/devices", headers=resident, json={"token": "rollback-device"})
    owned = upload(client, admin).json()
    foreign = upload(client, other).json()
    assert publish(client, admin, ids=[owned["id"], foreign["id"]]).status_code == 409
    assert client.get("/api/news", headers=resident).json() == {"items": [], "next_cursor": None}
    assert run(notifications()) == []
    initial = publish(client, admin, text="Исходная версия", ids=[owned["id"]]).json()
    new_media = upload(client, admin).json()
    failed = client.put(f"/api/news/{initial['id']}", headers=admin, json={
        "text": "Эта правка не должна сохраниться", "version": 1,
        "media_ids": [new_media["id"], foreign["id"]],
    })
    assert failed.status_code == 409
    preserved = client.get(f"/api/news/{initial['id']}", headers=resident).json()
    assert preserved["text"] == initial["text"] and preserved["version"] == 1
    assert [item["id"] for item in preserved["media"]] == [owned["id"]]
    assert client.get(owned["url"]).status_code == 200
    assert publish(client, admin, ids=[new_media["id"]]).status_code == 201
    assert publish(client, other, ids=[foreign["id"]]).status_code == 201
    assert len(run(notifications())) == 3  # Failed writes produced no notification jobs.


def test_simultaneous_edits_preserve_one_complete_winner(setup):
    client, admin, resident, other = setup
    post = publish(client, admin).json()
    attempts = [(admin, "Правка А"), (other, "Правка Б")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda edit: client.put(f"/api/news/{post['id']}", headers=edit[0],
                                                       json={"text": edit[1], "version": 1}), attempts))
    assert sorted(response.status_code for response in results) == [200, 409]
    winner = next(response.json() for response in results if response.status_code == 200)
    stored = client.get(f"/api/news/{post['id']}", headers=resident).json()
    assert stored["text"] == winner["text"] and stored["version"] == 2


def test_exact_upload_limit_multiple_parts_and_signed_scope(setup, monkeypatch):
    client, admin, _resident, _other = setup
    monkeypatch.setattr(news.settings, "news_max_upload_bytes", 2048)
    accepted = upload(client, admin, name="exact.bin", data=b"x" * 2048).json()
    assert accepted["size_bytes"] == 2048
    assert upload(client, admin, data=b"x" * 2049).status_code == 413
    multiple = client.post("/api/news/media", headers=admin,
                           files=[("file", ("a.txt", b"a")), ("file", ("b.txt", b"b"))])
    assert multiple.status_code == 400
    assert len(list(news_media.media_path(accepted["id"]).parent.glob("*.blob"))) == 1
    url = accepted["url"]
    for byte_range in ("bytes=", "bytes=-0", "bytes=5-2", "bytes=0-1,4-5", "bytes=" + "9" * 5000 + "-", "items=0-1"):
        response = client.get(url, headers={"Range": byte_range})
        assert response.status_code == 416 and response.headers["content-range"] == "bytes */2048"
    tampered = url[:-1] + ("1" if url[-1] != "1" else "2")
    assert client.get(tampered).status_code == 403
    assert client.get(url.replace("/content?", "/thumbnail?")).status_code == 403


@pytest.mark.parametrize("invalidation", ["blocked_user", "expired_post", "expired_device"])
def test_queued_push_rechecks_access_and_age_before_sending(setup, invalidation):
    client, admin, resident, _other = setup
    client.post("/api/news/devices", headers=resident, json={"token": "guarded-queue-device"})
    post = publish(client, admin).json()
    user_id = int(decode_token(resident["Authorization"].split(" ")[1])["sub"])

    async def invalidate():
        async with SessionLocal() as session:
            if invalidation == "blocked_user":
                await session.execute(update(User).where(User.id == user_id).values(is_active=False))
            elif invalidation == "expired_post":
                await session.execute(update(NewsPost).where(NewsPost.id == post["id"]).values(created_at=utcnow() - timedelta(days=2)))
            else:
                await session.execute(update(NewsDevice).values(updated_at=utcnow() - timedelta(days=31)))
            await session.commit()

    run(invalidate())
    sender = FakeSender()
    run(process_outbox_once(sender))
    assert sender.calls == [] and run(notifications())[0].status == "cancelled"


def test_device_account_switch_cancels_previous_queue_and_old_logout_is_harmless(setup):
    client, admin, resident, other = setup
    token = "shared-installation-token"
    client.post("/api/news/devices", headers=resident, json={"token": token})
    publish(client, admin)
    client.post("/api/news/devices", headers=other, json={"token": token})
    assert run(notifications())[0].status == "cancelled"
    client.request("DELETE", "/api/news/devices", headers=resident, json={"token": token})
    new_post = publish(client, admin).json()
    sender = FakeSender()
    assert run(process_outbox_once(sender)) == 1
    assert sender.calls == [(token, new_post["id"])]


def test_worker_recovers_expired_lease_and_stops_after_retry_budget(setup):
    client, admin, resident, _other = setup
    client.post("/api/news/devices", headers=resident, json={"token": "recoverable-device"})
    publish(client, admin)

    async def change_job(**values):
        async with SessionLocal() as session:
            latest_id = await session.scalar(select(NewsNotification.id).order_by(NewsNotification.id.desc()).limit(1))
            await session.execute(update(NewsNotification).where(NewsNotification.id == latest_id).values(**values))
            await session.commit()

    run(change_job(status="sending", lease_id="a" * 32, next_attempt_at=utcnow() + timedelta(minutes=1)))
    sender = FakeSender()
    assert run(process_outbox_once(sender)) == 0  # A still-running worker owns the lease.
    run(change_job(next_attempt_at=utcnow() - timedelta(seconds=1)))
    assert run(process_outbox_once(sender)) == 1 and len(sender.calls) == 1
    assert run(notifications())[0].status == "sent"
    publish(client, admin)
    run(change_job(attempts=11))
    failed_sender = FakeSender(failure=PushFailure("fcm_transport_unknown"))
    assert run(process_outbox_once(failed_sender)) == 1
    failed = run(notifications())[-1]
    assert failed.status == "failed" and failed.attempts == 12 and failed.sent_at is None
    assert run(process_outbox_once(failed_sender)) == 0


@pytest.mark.parametrize("status,error_code,expected", [
    (200, None, None), (404, "UNREGISTERED", "fcm_unregistered"),
    (403, "SENDER_ID_MISMATCH", "fcm_sender_mismatch"), (503, None, "fcm_http_503"),
    (0, None, "fcm_transport_unknown"),
])
def test_fcm_transport_payload_privacy_and_provider_errors(setup, monkeypatch, status, error_code, expected):
    _client, _admin, _resident, _other = setup
    captured = []
    original_client = httpx.AsyncClient

    def respond(request):
        captured.append(json.loads(request.content))
        if status == 0:
            raise httpx.ReadTimeout("Synthetic uncertain transport", request=request)
        if status == 200:
            return httpx.Response(200, json={"name": "projects/test/messages/accepted"})
        details = [{"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": error_code}] if error_code else []
        return httpx.Response(status, json={"error": {"details": details}})

    monkeypatch.setattr(news.settings, "news_fcm_service_account_file", "configured-test-only")
    monkeypatch.setattr(news_notifications.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    sender = news_notifications.FcmSender()
    sender.credentials = SimpleNamespace(valid=True, token="local-test-oauth", project_id="test-project")
    private_text = "PRIVATE CONTENT MUST NOT APPEAR ON LOCK SCREEN"
    post = NewsPost(id=42, text=private_text)
    if expected:
        with pytest.raises(PushFailure) as caught:
            run(sender.send("local-test-device", post))
        assert caught.value.code == expected
        assert caught.value.invalid_token is (error_code == "UNREGISTERED")
        assert caught.value.permanent is (error_code in {"UNREGISTERED", "SENDER_ID_MISMATCH"})
    else:
        run(sender.send("local-test-device", post))
    message = captured[0]["message"]
    assert private_text not in json.dumps(message)
    assert message["data"] == {"screen": "news", "news_id": "42"}
    assert message["android"]["notification"]["channel_id"] == "news"
    assert message["android"]["notification"]["tag"] == "news-42"
