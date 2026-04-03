from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .utils.input_safety import (
    normalize_full_name,
    normalize_login,
    normalize_password,
    normalize_phone_key,
    normalize_plot_number,
    normalize_vehicle_number,
)


class MessageResponse(BaseModel):
    message: str


class UserResponse(BaseModel):
    id: int
    phone: str
    name: str | None = None
    apartment: str | None = None
    is_admin: bool = False


class LoginRequest(BaseModel):
    login: str
    password: str

    @field_validator("login")
    @classmethod
    def validate_login(cls, value: str) -> str:
        return normalize_login(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return normalize_password(value)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class OpenGateRequest(BaseModel):
    access_point_id: int


class OpenGateResponse(BaseModel):
    success: bool
    message: str


class CreateRequestRequest(BaseModel):
    key_type: Literal["Phone", "VehicleNumber"]
    key_value: str
    access_point_ids: list[int] = Field(min_length=1)
    is_permanent: bool = False
    is_courier: bool = False
    hours: int | None = Field(default=None, ge=1, le=24 * 365)
    plot_number: str | None = None

    @field_validator("plot_number")
    @classmethod
    def validate_plot_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_plot_number(value)

    @model_validator(mode="after")
    def validate_key_value(self) -> "CreateRequestRequest":
        if self.key_type == "Phone":
            self.key_value = normalize_phone_key(self.key_value)
        else:
            self.key_value = normalize_vehicle_number(self.key_value)
        return self


class RequestResponse(BaseModel):
    id: int
    resident_id: int
    key_type: str
    key_value: str
    is_permanent: bool
    expires_at: datetime | None
    status: str
    created_at: datetime


class AccessPointResponse(BaseModel):
    id: int
    name: str


# Compatibility DTOs for current RN app
class CompatUser(BaseModel):
    id: str
    login: str
    fullName: str
    plotNumber: str


class CompatAuthResult(BaseModel):
    success: bool
    user: CompatUser | None = None
    error: str | None = None
    access_token: str | None = None
    requiresProfileCompletion: bool = False


class CompatUpdateProfilePayload(BaseModel):
    fullName: str = Field(min_length=2, max_length=120)
    plotNumber: str | None = Field(default=None, max_length=20)

    @field_validator("fullName")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return normalize_full_name(value)

    @field_validator("plotNumber")
    @classmethod
    def validate_plot_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_plot_number(value)


class CompatLoginPayload(BaseModel):
    login: str
    password: str

    @field_validator("login")
    @classmethod
    def validate_login(cls, value: str) -> str:
        return normalize_login(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return normalize_password(value)


class CompatCreatePassPayload(BaseModel):
    carNumber: str
    plotNumber: str
    expiresAt: str | None
    isPermanent: bool

    @field_validator("carNumber")
    @classmethod
    def validate_car_number(cls, value: str) -> str:
        return normalize_vehicle_number(value)

    @field_validator("plotNumber")
    @classmethod
    def validate_plot_number(cls, value: str) -> str:
        return normalize_plot_number(value)


class CompatPassItem(BaseModel):
    id: str
    carNumber: str
    plotNumber: str
    expiresAt: str | None
    isPermanent: bool
    status: Literal["active", "expired", "permanent"]
    createdAt: str


class CompatOpenActionRequest(BaseModel):
    action: Literal["entry", "exit", "wicket_north", "wicket_lake", "wicket_admin", "wicket_forest"]


class CompatGateActionResult(BaseModel):
    success: bool
    action: str
    message: str
    timestamp: int


class ApiError(BaseModel):
    code: str
    message: str


class AccessPointMyResponse(BaseModel):
    id: int
    name: str
    code: str
    type: str


class OpenAccessRequest(BaseModel):
    access_point_id: int


class OpenAccessResponse(BaseModel):
    status: Literal["success", "failed", "pending"]
    message: str
    request_id: str


class AccessEventItem(BaseModel):
    request_id: str
    access_point_id: int | None
    status: str
    action: str
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
