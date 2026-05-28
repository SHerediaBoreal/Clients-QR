from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import normalize_phone


class PublicRegisterPayload(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=40)
    email: EmailStr | None = None
    google_sub: str | None = None
    public_token: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_optional_email(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        normalized = normalize_phone(value)
        if not normalized:
            raise ValueError("El teléfono es obligatorio.")
        if len(normalized) < 7 or len(normalized) > 15:
            raise ValueError("El teléfono debe tener entre 7 y 15 dígitos.")
        return normalized


class PublicRegisterResponse(BaseModel):
    status: str
    message: str
    purchase_id: int | None = None
    customer_id: int | None = None


class PurchaseSummary(BaseModel):
    id: int
    customer_id: int | None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    purchase_date: datetime
    status: str
    source_token: str | None = None


class CustomerSummary(BaseModel):
    id: int
    first_name: str
    last_name: str
    phone: str | None = None
    email: str | None = None
    latest_purchase_date: datetime | None = None
    total_purchases: int = 0
    pending_purchases: int = 0
    approved_purchases: int = 0
    rejected_purchases: int = 0
    failed_purchases: int = 0


class StatsPayload(BaseModel):
    total_interactions: int
    success_interactions: int
    failed_interactions: int
    total_purchases: int
    pending_purchases: int
    approved_purchases: int
    rejected_purchases: int
    failed_purchases: int
    unique_customers: int
    active_customers: int
    inactive_customers: int
    conversion_rate: float
    date_from: datetime | None = None
    date_to: datetime | None = None
