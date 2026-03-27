from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    apartment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    gate_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Compatibility auth fields for current mobile UI.
    login: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plot_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    requests: Mapped[list["Request"]] = relationship(back_populates="resident")
    logs: Mapped[list["Log"]] = relationship(back_populates="user")
    access_keys: Mapped[list["AccessKey"]] = relationship(back_populates="user")
    access_permissions: Mapped[list["AccessPermission"]] = relationship(back_populates="user")
    access_events: Mapped[list["AccessEventLog"]] = relationship(back_populates="user")


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key_type: Mapped[str] = mapped_column(String(20), nullable=False)
    key_value: Mapped[str] = mapped_column(String(50), nullable=False)
    gate_key_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    access_point_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    is_permanent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plot_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    resident: Mapped[User] = relationship(back_populates="requests")


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    access_point_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User | None] = relationship(back_populates="logs")


class AccessKey(Base):
    __tablename__ = "access_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    protocol_type: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    facility_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    card_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="access_keys")
    permissions: Mapped[list["AccessPermission"]] = relationship(back_populates="key")
    events: Mapped[list["AccessEventLog"]] = relationship(back_populates="key")


class AccessPoint(Base):
    __tablename__ = "access_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), default="gate", nullable=False)
    controller_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    permissions: Mapped[list["AccessPermission"]] = relationship(back_populates="access_point")
    events: Mapped[list["AccessEventLog"]] = relationship(back_populates="access_point")


class AccessPermission(Base):
    __tablename__ = "access_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    access_point_id: Mapped[int] = mapped_column(
        ForeignKey("access_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_id: Mapped[int] = mapped_column(ForeignKey("access_keys.id", ondelete="CASCADE"), nullable=False, index=True)
    is_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="access_permissions")
    access_point: Mapped[AccessPoint] = relationship(back_populates="permissions")
    key: Mapped[AccessKey] = relationship(back_populates="permissions")


class AccessEventLog(Base):
    __tablename__ = "access_event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    access_point_id: Mapped[int] = mapped_column(
        ForeignKey("access_points.id", ondelete="SET NULL"), nullable=True, index=True
    )
    key_id: Mapped[int | None] = mapped_column(ForeignKey("access_keys.id", ondelete="SET NULL"), nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    action: Mapped[str] = mapped_column(String(50), default="open", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[User] = relationship(back_populates="access_events")
    access_point: Mapped[AccessPoint | None] = relationship(back_populates="events")
    key: Mapped[AccessKey | None] = relationship(back_populates="events")
