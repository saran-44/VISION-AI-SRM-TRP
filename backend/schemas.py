from __future__ import annotations

import re
from datetime import date as Date, datetime as DateTime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BUS_NUMBER_RE = re.compile(r"^[A-Z0-9][A-Z0-9 ._-]{0,19}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CONTROL_RE = re.compile(r"[\x00-\x1f<>]")


def normalize_bus_number(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().upper())


def clean_text(value: str) -> str:
    value = value.strip()
    if CONTROL_RE.search(value):
        raise ValueError("Text contains unsupported control or markup characters")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginSchema(StrictModel):
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_RE.pattern)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class FirebaseTokenSchema(StrictModel):
    """The Firebase ID token handed over after a successful Firebase sign-in."""

    id_token: str = Field(min_length=20, max_length=8192)


class DriverBase(StrictModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str | None = Field(default=None, min_length=7, max_length=25, pattern=r"^[+0-9()\- ]+$")
    bus_number: str = Field(min_length=1, max_length=20)
    license_number: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=300)
    active: bool = True

    @field_validator("name", "license_number", "notes", "bus_number")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        return clean_text(value) if value is not None else None

    @field_validator("bus_number")
    @classmethod
    def validate_bus_number(cls, value: str) -> str:
        value = normalize_bus_number(value)
        if not BUS_NUMBER_RE.fullmatch(value):
            raise ValueError("Use letters, numbers, spaces, dot, dash or underscore only")
        return value


class DriverCreate(DriverBase):
    pass


class DriverUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    phone: str | None = Field(default=None, min_length=7, max_length=25, pattern=r"^[+0-9()\- ]+$")
    bus_number: str | None = Field(default=None, min_length=1, max_length=20)
    license_number: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=300)
    active: bool | None = None

    @field_validator("name", "license_number", "notes", "bus_number")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        return clean_text(value) if value is not None else None

    @field_validator("bus_number")
    @classmethod
    def validate_bus_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = normalize_bus_number(value)
        if not BUS_NUMBER_RE.fullmatch(value):
            raise ValueError("Use letters, numbers, spaces, dot, dash or underscore only")
        return value


class BusBase(StrictModel):
    bus_number: str = Field(min_length=1, max_length=20)
    registration_number: str | None = Field(default=None, max_length=60)
    route: str | None = Field(default=None, max_length=120)
    capacity: int = Field(default=40, ge=1, le=120)
    insurance_expiry: Date | None = None
    status: Literal["active", "maintenance", "retired"] = "active"
    notes: str | None = Field(default=None, max_length=300)

    @field_validator("bus_number")
    @classmethod
    def validate_bus_number(cls, value: str) -> str:
        value = normalize_bus_number(value)
        if not BUS_NUMBER_RE.fullmatch(value):
            raise ValueError("Use letters, numbers, spaces, dot, dash or underscore only")
        return value

    @field_validator("registration_number", "route", "notes")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        return clean_text(value) if value is not None else None


class BusCreate(BusBase):
    pass


class BusUpdate(StrictModel):
    bus_number: str | None = Field(default=None, min_length=1, max_length=20)
    registration_number: str | None = Field(default=None, max_length=60)
    route: str | None = Field(default=None, max_length=120)
    capacity: int | None = Field(default=None, ge=1, le=120)
    insurance_expiry: Date | None = None
    status: Literal["active", "maintenance", "retired"] | None = None
    notes: str | None = Field(default=None, max_length=300)

    @field_validator("bus_number")
    @classmethod
    def validate_bus_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = normalize_bus_number(value)
        if not BUS_NUMBER_RE.fullmatch(value):
            raise ValueError("Use letters, numbers, spaces, dot, dash or underscore only")
        return value

    @field_validator("registration_number", "route", "notes")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        return clean_text(value) if value is not None else None


class EventCreate(StrictModel):
    bus_number: str = Field(min_length=1, max_length=20)
    direction: Literal["IN", "OUT"]
    gate: str = Field(min_length=1, max_length=60)
    camera_id: str = Field(min_length=1, max_length=60)
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: DateTime

    @field_validator("direction", mode="before")
    @classmethod
    def normalize_direction(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("bus_number")
    @classmethod
    def validate_bus_number(cls, value: str) -> str:
        value = normalize_bus_number(value)
        if not BUS_NUMBER_RE.fullmatch(value):
            raise ValueError("Use letters, numbers, spaces, dot, dash or underscore only")
        return value

    @field_validator("gate", "camera_id")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return clean_text(value)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: DateTime) -> DateTime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        if value > DateTime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("timestamp cannot be more than five minutes in the future")
        return value


class EventFilter(StrictModel):
    date: Date | None = None
    date_from: DateTime | None = None
    date_to: DateTime | None = None
    bus_number: str | None = Field(default=None, max_length=20)
    gate: str | None = Field(default=None, max_length=60)
    direction: Literal["IN", "OUT"] | None = None
    flagged: bool | None = None
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=50, ge=1, le=200)

    @field_validator("direction", mode="before")
    @classmethod
    def normalize_direction(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().upper()
            return value or None
        return value

    @field_validator("bus_number")
    @classmethod
    def normalize_bus(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = normalize_bus_number(value)
        if not BUS_NUMBER_RE.fullmatch(value):
            raise ValueError("Invalid bus number")
        return value

    @field_validator("gate")
    @classmethod
    def validate_gate(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return clean_text(value)

    @field_validator("date_from", "date_to")
    @classmethod
    def normalize_range(cls, value: DateTime | None) -> DateTime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_dates(self) -> "EventFilter":
        if self.date and (self.date_from or self.date_to):
            raise ValueError("Use either date or date_from/date_to, not both")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be before date_to")
        return self


class SearchFilter(StrictModel):
    q: str | None = Field(default=None, max_length=80)
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=25, ge=1, le=100)

    @field_validator("q")
    @classmethod
    def validate_q(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return clean_text(value)


class AnalyticsFilter(StrictModel):
    hours: int = Field(default=24, ge=1, le=168)
    date: Date | None = None
    bus_number: str | None = Field(default=None, max_length=20)
    gate: str | None = Field(default=None, max_length=60)
    direction: Literal["IN", "OUT"] = "IN"

    @field_validator("direction", mode="before")
    @classmethod
    def normalize_direction(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("bus_number")
    @classmethod
    def normalize_bus(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = normalize_bus_number(value)
        if not BUS_NUMBER_RE.fullmatch(value):
            raise ValueError("Invalid bus number")
        return value

    @field_validator("gate")
    @classmethod
    def validate_gate(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return clean_text(value)
