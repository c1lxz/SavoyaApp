"""Additive news schema. Existing access-control tables are never altered."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NewsPost(Base):
    __tablename__ = "news_posts"
    __table_args__ = (UniqueConstraint("author_id", "request_id", name="uq_news_request"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author_name: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NewsMedia(Base):
    __tablename__ = "news_media"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("news_posts.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer)
    has_thumbnail: Mapped[bool] = mapped_column(default=False)
    available: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    detached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class NewsDevice(Base):
    __tablename__ = "news_devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(4096), unique=True)
    platform: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NewsNotification(Base):
    __tablename__ = "news_notifications"
    __table_args__ = (UniqueConstraint("post_id", "device_id", name="uq_news_notification"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("news_posts.id"))
    device_id: Mapped[int] = mapped_column(ForeignKey("news_devices.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    lease_id: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NewsPoll(Base):
    __tablename__ = "news_polls"
    # One optional poll per post, without changing any existing news columns.
    id: Mapped[int] = mapped_column(ForeignKey("news_posts.id", ondelete="CASCADE"), primary_key=True)
    question: Mapped[str] = mapped_column(String(300))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NewsPollOption(Base):
    __tablename__ = "news_poll_options"
    __table_args__ = (
        UniqueConstraint("id", "poll_id", name="uq_news_poll_option_parent"),
        # A stale client must not vote for a new answer reusing an old answer ID.
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("news_polls.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(200))


class NewsPollVote(Base):
    __tablename__ = "news_poll_votes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["option_id", "poll_id"], ["news_poll_options.id", "news_poll_options.poll_id"],
            ondelete="CASCADE", name="fk_news_poll_vote_option",
        ),
    )
    # Composite primary key enforces a single current answer per account.
    poll_id: Mapped[int] = mapped_column(ForeignKey("news_polls.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    option_id: Mapped[int] = mapped_column(Integer, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
