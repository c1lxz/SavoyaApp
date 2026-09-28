"""Poll mutations share the parent post's database lock, including edit/delete."""
from __future__ import annotations

import unicodedata

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..news_models import NewsPoll, NewsPollOption, NewsPollVote, NewsPost, utcnow
from ..utils.datetime import ensure_utc_datetime


class PollDefinition(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=10)

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("options")
    @classmethod
    def validate_options(cls, values):
        trimmed = [value.strip() for value in values]
        if any(not value or len(value) > 200 for value in trimmed):
            raise ValueError("Вариант ответа должен содержать от 1 до 200 символов")
        keys = [" ".join(unicodedata.normalize("NFKC", value).casefold().split()) for value in trimmed]
        if len(set(keys)) != len(keys):
            raise ValueError("Варианты ответа должны отличаться")
        return trimmed


class PollVoteBody(BaseModel):
    option_id: int = Field(ge=1, strict=True)


async def serialize_polls(session: AsyncSession, post_ids: list[int], user_id: int) -> dict[int, dict]:
    """Two queries per page, with grouped counts and only the caller's answer."""
    if not post_ids:
        return {}
    rows = (await session.execute(select(NewsPoll.id, NewsPoll.question, NewsPoll.started_at, NewsPoll.closed_at).where(
        NewsPoll.id.in_(post_ids),
    ))).all()
    if not rows:
        return {}
    polls = {row.id: {
        "id": row.id, "question": row.question, "options": [], "total_votes": 0,
        "my_option_id": None, "is_closed": row.closed_at is not None,
        "closed_at": ensure_utc_datetime(row.closed_at),
        "can_edit": row.closed_at is None and row.started_at is None,
    } for row in rows}
    options = (await session.execute(select(
        NewsPollOption.id, NewsPollOption.poll_id, NewsPollOption.text,
        func.count(NewsPollVote.user_id).label("votes"),
        func.max(case((NewsPollVote.user_id == user_id, 1), else_=0)).label("mine"),
    ).outerjoin(NewsPollVote, (NewsPollVote.option_id == NewsPollOption.id)
                & (NewsPollVote.poll_id == NewsPollOption.poll_id)).where(
        NewsPollOption.poll_id.in_(list(polls)),
    ).group_by(NewsPollOption.id, NewsPollOption.poll_id, NewsPollOption.text, NewsPollOption.position)
      .order_by(NewsPollOption.poll_id, NewsPollOption.position))).all()
    for option in options:
        poll = polls[option.poll_id]
        poll["options"].append({"id": option.id, "text": option.text, "votes": option.votes})
        poll["total_votes"] += option.votes
        if option.mine:
            poll["my_option_id"] = option.id
    for poll in polls.values():
        poll["can_edit"] = poll["can_edit"] and poll["total_votes"] == 0
    return polls


async def lock_active_post(session: AsyncSession, post_id: int) -> None:
    # SELECT FOR UPDATE alone does not lock on SQLite. This no-op UPDATE acquires
    # its write lock and a PostgreSQL row lock, also serializing against post CAS
    # edits/deletion, without invalidating a text editor's version on every vote.
    result = await session.execute(update(NewsPost).where(
        NewsPost.id == post_id, NewsPost.deleted_at.is_(None),
    ).values(version=NewsPost.version).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(404, "Новость не найдена")


async def require_current_actor(
    session: AsyncSession, user_id: int, auth_generation: str | None, *, admin: bool = False,
) -> None:
    # Authentication may have run before this request waited for the post write
    # lock. Re-read scalar columns (not the cached ORM User) so a deleted/blocked
    # account or a recycled SQLite user ID cannot cast a late vote. NULL matches
    # existing installations; newly created accounts have a distinct generation.
    actor = (await session.execute(select(User.is_admin, User.staff_role).where(
        User.id == user_id, User.is_active.is_(True),
        User.auth_generation.is_(None) if auth_generation is None else User.auth_generation == auth_generation,
    ))).one_or_none()
    if actor is None:
        raise HTTPException(401, "Учётная запись недоступна. Войдите заново")
    if admin and not (actor.is_admin and actor.staff_role in (None, "administration")):
        raise HTTPException(403, "Admin access required")


async def set_poll_definition(session: AsyncSession, post_id: int, definition: PollDefinition | None) -> None:
    """Caller already inserted or locked the post. Omitted poll never calls here."""
    poll = await session.get(NewsPoll, post_id, populate_existing=True)
    if poll is not None:
        existing = list((await session.scalars(select(NewsPollOption.text).where(
            NewsPollOption.poll_id == post_id,
        ).order_by(NewsPollOption.position))).all())
        if definition is not None and definition.question == poll.question and definition.options == existing:
            return  # Exact no-op also preserves IDs/votes after voting has started.
        voted = await session.scalar(select(NewsPollVote.user_id).where(NewsPollVote.poll_id == post_id).limit(1))
        if poll.closed_at is not None or poll.started_at is not None or voted is not None:
            raise HTTPException(409, "Опрос уже закрыт или получил голоса. Можно изменить только текст новости")
        await session.execute(delete(NewsPollOption).where(NewsPollOption.poll_id == post_id))
        if definition is None:
            await session.delete(poll)
            await session.flush()
            return
        poll.question = definition.question
    elif definition is not None:
        session.add(NewsPoll(id=post_id, question=definition.question))
    else:
        return
    await session.flush()
    session.add_all([NewsPollOption(poll_id=post_id, position=index, text=text)
                     for index, text in enumerate(definition.options)])
    await session.flush()


async def vote(
    session: AsyncSession, post_id: int, user_id: int, option_id: int, *, auth_generation: str | None = None,
) -> dict:
    await lock_active_post(session, post_id)
    await require_current_actor(session, user_id, auth_generation)
    poll = await session.get(NewsPoll, post_id, populate_existing=True)
    if poll is None:
        raise HTTPException(404, "Опрос не найден")
    if poll.closed_at is not None:
        raise HTTPException(409, "Голосование завершено")
    valid = await session.scalar(select(NewsPollOption.id).where(
        NewsPollOption.id == option_id, NewsPollOption.poll_id == post_id,
    ))
    if valid is None:
        raise HTTPException(422, "Вариант ответа недоступен. Обновите новость")
    # The definition stays immutable even if every voter account is later
    # deleted and its votes are removed by explicit account cleanup.
    if poll.started_at is None:
        poll.started_at = utcnow()
    # The parent lock makes this database-portable upsert atomic across workers;
    # the composite PK independently forbids two votes for one account/poll.
    changed = await session.execute(update(NewsPollVote).where(
        NewsPollVote.poll_id == post_id, NewsPollVote.user_id == user_id,
    ).values(option_id=option_id, updated_at=utcnow()))
    if changed.rowcount == 0:
        session.add(NewsPollVote(poll_id=post_id, user_id=user_id, option_id=option_id))
    await session.flush()
    result = (await serialize_polls(session, [post_id], user_id))[post_id]
    await session.commit()
    return result


async def close(
    session: AsyncSession, post_id: int, user_id: int, *, auth_generation: str | None = None,
) -> dict:
    await lock_active_post(session, post_id)
    await require_current_actor(session, user_id, auth_generation, admin=True)
    poll = await session.get(NewsPoll, post_id, populate_existing=True)
    if poll is None:
        raise HTTPException(404, "Опрос не найден")
    if poll.closed_at is None:
        poll.closed_at = utcnow()
        await session.flush()
    result = (await serialize_polls(session, [post_id], user_id))[post_id]
    await session.commit()
    return result
