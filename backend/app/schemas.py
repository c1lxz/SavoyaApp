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
    password_change_required: bool = False


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
    phone_number: str | None = None
    resident_name: str | None = None
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

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_phone_key(value)

    @field_validator("resident_name")
    @classmethod
    def validate_resident_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            return None
        return normalize_full_name(value)

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
    phone_number: str | None = None
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
    phoneNumber: str
    isAdmin: bool = False
    passwordChangeRequired: bool = False


class CompatAuthResult(BaseModel):
    success: bool
    user: CompatUser | None = None
    error: str | None = None
    access_token: str | None = None
    requiresProfileCompletion: bool = False
    passwordChangeRequired: bool = False


class CompatRegisterAccountPayload(BaseModel):
    fullName: str = Field(min_length=2, max_length=120)
    phoneNumber: str = Field(min_length=7, max_length=32)
    plotNumber: str = Field(min_length=1, max_length=20)

    @field_validator("fullName")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return normalize_full_name(value)

    @field_validator("phoneNumber")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        return normalize_phone_key(value)

    @field_validator("plotNumber")
    @classmethod
    def validate_plot_number(cls, value: str) -> str:
        return normalize_plot_number(value)


class CompatRegisterAccountResult(BaseModel):
    success: bool = True
    login: str
    password: str
    user: CompatUser


class CompatChangePasswordPayload(BaseModel):
    newPassword: str
    repeatPassword: str

    @field_validator("newPassword", "repeatPassword")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return normalize_password(value)

    @model_validator(mode="after")
    def validate_password_match(self) -> "CompatChangePasswordPayload":
        if self.newPassword != self.repeatPassword:
            raise ValueError("Passwords do not match")
        return self


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
    carNumber: str | None = None
    residentName: str | None = None
    plotNumber: str
    phoneNumber: str | None = None
    expiresAt: str | None
    isPermanent: bool
    isCourier: bool = False

    @field_validator("carNumber", mode="before")
    @classmethod
    def normalize_optional_car_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("phoneNumber", mode="before")
    @classmethod
    def normalize_optional_phone_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("residentName", mode="before")
    @classmethod
    def normalize_optional_resident_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("carNumber")
    @classmethod
    def validate_car_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_vehicle_number(value)

    @field_validator("plotNumber")
    @classmethod
    def validate_plot_number(cls, value: str) -> str:
        return normalize_plot_number(value)

    @field_validator("phoneNumber")
    @classmethod
    def validate_phone_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_phone_key(value)

    @field_validator("residentName")
    @classmethod
    def validate_resident_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_full_name(value)

    @model_validator(mode="after")
    def validate_key_presence(self) -> "CompatCreatePassPayload":
        if not self.carNumber and not self.phoneNumber:
            raise ValueError("Either carNumber or phoneNumber must be provided")
        return self


class CompatPassItem(BaseModel):
    id: str
    keyType: Literal["Phone", "VehicleNumber"]
    keyValue: str
    carNumber: str | None = None
    plotNumber: str
    phoneNumber: str | None = None
    expiresAt: str | None
    isPermanent: bool
    isCourier: bool = False
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
    details: dict | None = None
    created_at: datetime


class AdminResidentSummary(BaseModel):
    id: int
    login: str | None = None
    full_name: str | None = None
    phone: str
    plot_number: str | None = None


class AdminRequestItem(BaseModel):
    id: int
    resident: AdminResidentSummary
    key_type: str
    key_value: str
    country_label: str | None = None
    phone_number: str | None = None
    access_point_ids: list[int]
    gate_key_id: int | None = None
    is_permanent: bool
    is_courier: bool
    expires_at: datetime | None = None
    status: str
    created_at: datetime
    cancelled_at: datetime | None = None
    plot_number: str | None = None


class AdminRequestListResponse(BaseModel):
    total: int
    items: list[AdminRequestItem]


class AdminUserItem(BaseModel):
    id: int
    login: str
    password: str | None = None
    full_name: str | None = None
    phone: str
    plot_number: str | None = None
    owner_index: int | None = None
    is_active: bool
    password_change_required: bool = False
    created_at: datetime


class AdminUserListResponse(BaseModel):
    total: int
    items: list[AdminUserItem]


class AdminCreateUserPayload(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=32)
    plot_number: str = Field(min_length=1, max_length=20)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return normalize_full_name(value)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone_key(value)

    @field_validator("plot_number")
    @classmethod
    def validate_plot_number(cls, value: str) -> str:
        return normalize_plot_number(value)


class AdminMonitorEventItem(BaseModel):
    id: str
    source: Literal["app", "gate"]
    created_at: datetime
    status: str
    action: str
    message: str | None = None
    actor_user_id: int | None = None
    actor_login: str | None = None
    actor_name: str | None = None
    actor_phone: str | None = None
    access_point_id: int | None = None
    access_point_name: str | None = None
    key_type: str | None = None
    key_value: str | None = None
    request_id: str | None = None
    app_request_id: int | None = None
    gate_key_id: int | None = None
    gate_event_index: int | None = None
    gate_event_code: int | None = None
    gate_user_ptr: int | None = None
    gate_name: str | None = None
    gate_original_name: str | None = None
    gate_unit: str | None = None
    details: dict | None = None


class AdminMonitorResponse(BaseModel):
    total: int
    items: list[AdminMonitorEventItem]
    gate_error: str | None = None
