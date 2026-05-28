from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.security import hash_value, normalize_email, normalize_phone, utcnow
from app.models import AdminUser, AuditLog, Customer, CustomerIdentity, Purchase, RegistrationAttempt


class NotFoundError(Exception):
    pass


class PermissionError(Exception):
    pass


@dataclass(slots=True)
class RegistrationResult:
    success: bool
    message: str
    customer: Customer | None = None
    purchase: Purchase | None = None
    attempt: RegistrationAttempt | None = None


CUSTOMER_TIERS = ("VIP", "alto", "medio", "bajo")


def normalize_customer_tier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized not in CUSTOMER_TIERS:
        raise ValueError("Tier de cliente invalido")
    return normalized


def parse_optional_non_negative_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        if value < 0:
            raise ValueError("El monto debe ser un entero mayor o igual a 0")
        return value
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError("El monto debe ser un entero mayor o igual a 0") from exc
    if parsed < 0:
        raise ValueError("El monto debe ser un entero mayor o igual a 0")
    return parsed


def seed_admin_users(db: Session, emails: list[str], local_accounts: list[tuple[str, str]] | None = None) -> None:
    merged_accounts: dict[str, str | None] = {}
    for email in emails:
        normalized = normalize_email(email)
        if normalized:
            merged_accounts.setdefault(normalized, None)
    for email, phone in local_accounts or []:
        normalized_email = normalize_email(email)
        normalized_phone = normalize_phone(phone)
        if not normalized_email or not normalized_phone:
            continue
        merged_accounts[normalized_email] = hash_value(normalized_phone)

    for email, phone_hash in merged_accounts.items():
        exists = db.scalar(select(AdminUser).where(AdminUser.email == email))
        if exists is None:
            db.add(AdminUser(email=email, phone_hash=phone_hash, role="admin", active=True))
        elif phone_hash and exists.phone_hash != phone_hash:
            exists.phone_hash = phone_hash
    db.commit()


def write_audit(
    db: Session,
    *,
    actor_email: str | None,
    action: str,
    entity_type: str,
    entity_id: str,
    before: Any | None,
    after: Any | None,
) -> None:
    db.add(
        AuditLog(
            actor_email=normalize_email(actor_email),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=json.dumps(before, default=str, ensure_ascii=False) if before is not None else None,
            after_json=json.dumps(after, default=str, ensure_ascii=False) if after is not None else None,
        )
    )


def admin_is_allowed(db: Session, email: str) -> bool:
    normalized = normalize_email(email)
    if not normalized:
        return False
    user = db.scalar(select(AdminUser).where(AdminUser.email == normalized, AdminUser.active.is_(True)))
    return user is not None


def admin_local_login_allowed(db: Session, email: str, phone: str) -> bool:
    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone(phone)
    if not normalized_email or not normalized_phone:
        return False
    user = db.scalar(select(AdminUser).where(AdminUser.email == normalized_email, AdminUser.active.is_(True)))
    if user is None or user.phone_hash is None:
        return False
    return user.phone_hash == hash_value(normalized_phone)


def get_or_create_customer(
    db: Session,
    *,
    first_name: str,
    last_name: str,
    phone: str | None,
    email: str | None,
    google_sub: str | None,
) -> Customer:
    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone(phone)
    normalized_google_sub = google_sub.strip() if google_sub else None

    candidate: Customer | None = None

    if normalized_google_sub:
        candidate = db.scalar(select(Customer).where(Customer.google_sub == normalized_google_sub))

    if candidate is None and normalized_email:
        candidate = db.scalar(select(Customer).where(Customer.email == normalized_email))

    if candidate is None and normalized_phone:
        candidate = db.scalar(select(Customer).where(Customer.phone == normalized_phone))

    if candidate is None:
        candidate = Customer(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            phone=normalized_phone,
            email=normalized_email,
            google_sub=normalized_google_sub,
            status="active",
        )
        db.add(candidate)
        db.flush()
    else:
        if first_name.strip() and not candidate.first_name:
            candidate.first_name = first_name.strip()
        if last_name.strip() and not candidate.last_name:
            candidate.last_name = last_name.strip()
        if normalized_phone and not candidate.phone:
            candidate.phone = normalized_phone
        if normalized_email and not candidate.email:
            candidate.email = normalized_email
        if normalized_google_sub and not candidate.google_sub:
            candidate.google_sub = normalized_google_sub

    if normalized_google_sub:
        identity = db.scalar(
            select(CustomerIdentity).where(
                CustomerIdentity.provider == "google",
                CustomerIdentity.provider_subject == normalized_google_sub,
            )
        )
        if identity is None:
            db.add(
                CustomerIdentity(
                    customer=candidate,
                    provider="google",
                    provider_subject=normalized_google_sub,
                    provider_email=normalized_email,
                    verified_at=utcnow(),
                )
            )

    db.flush()
    return candidate


def update_customer_tier(
    db: Session,
    *,
    customer_id: int,
    tier: str | None,
    actor_email: str | None,
) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Cliente no encontrado")

    normalized_tier = normalize_customer_tier(tier)
    before = {"tier": customer.tier}
    customer.tier = normalized_tier
    write_audit(
        db,
        actor_email=actor_email,
        action="update_customer_tier",
        entity_type="customer",
        entity_id=str(customer.id),
        before=before,
        after={"tier": customer.tier},
    )
    db.commit()
    db.refresh(customer)
    return customer


def update_purchase_details(
    db: Session,
    *,
    purchase_id: int,
    description: str | None,
    amount: str | int | None,
    actor_email: str | None,
) -> Purchase:
    purchase = db.get(Purchase, purchase_id)
    if purchase is None:
        raise NotFoundError("Compra no encontrada")

    normalized_description = description.strip() if description and description.strip() else None
    normalized_amount = parse_optional_non_negative_int(amount)
    before = {"description": purchase.description, "amount": purchase.amount}
    purchase.description = normalized_description
    purchase.amount = normalized_amount
    write_audit(
        db,
        actor_email=actor_email,
        action="update_purchase_details",
        entity_type="purchase",
        entity_id=str(purchase.id),
        before=before,
        after={"description": purchase.description, "amount": purchase.amount},
    )
    db.commit()
    db.refresh(purchase)
    return purchase


def create_registration_attempt(
    db: Session,
    *,
    customer_id: int | None,
    status: str,
    failure_reason: str | None,
    source: str,
    request_ip: str | None,
    user_agent: str | None,
) -> RegistrationAttempt:
    attempt = RegistrationAttempt(
        customer_id=customer_id,
        status=status,
        failure_reason=failure_reason,
        source=source,
        ip_hash=hash_value(request_ip),
        user_agent_hash=hash_value(user_agent),
    )
    db.add(attempt)
    db.flush()
    return attempt


def create_purchase(
    db: Session,
    *,
    customer_id: int | None,
    status: str,
    source_token: str | None,
    purchase_date: datetime | None = None,
    description: str | None = None,
    amount: int | None = None,
    notes: str | None = None,
) -> Purchase:
    purchase = Purchase(
        customer_id=customer_id,
        purchase_date=purchase_date or utcnow(),
        status=status,
        source_token=source_token,
        description=description,
        amount=amount,
        notes=notes,
    )
    db.add(purchase)
    db.flush()
    return purchase


def register_public_purchase(
    db: Session,
    *,
    first_name: str,
    last_name: str,
    phone: str,
    email: str | None,
    google_sub: str | None,
    public_token: str,
    request_ip: str | None,
    user_agent: str | None,
) -> RegistrationResult:
    first_name = first_name.strip()
    last_name = last_name.strip()
    phone_norm = normalize_phone(phone)
    email_norm = normalize_email(email)
    google_sub_norm = google_sub.strip() if google_sub else None

    if not first_name or not last_name or not phone_norm:
        attempt = create_registration_attempt(
            db,
            customer_id=None,
            status="failure",
            failure_reason="Datos incompletos",
            source="qr_public",
            request_ip=request_ip,
            user_agent=user_agent,
        )
        purchase = create_purchase(
            db,
            customer_id=None,
            status="failed",
            source_token=public_token,
            notes="Datos incompletos",
        )
        db.commit()
        return RegistrationResult(False, "Registro fallido", None, purchase, attempt)

    customer = get_or_create_customer(
        db,
        first_name=first_name,
        last_name=last_name,
        phone=phone_norm,
        email=email_norm,
        google_sub=google_sub_norm,
    )

    attempt = create_registration_attempt(
        db,
        customer_id=customer.id,
        status="success",
        failure_reason=None,
        source="qr_public",
        request_ip=request_ip,
        user_agent=user_agent,
    )
    purchase = create_purchase(
        db,
        customer_id=customer.id,
        status="pending",
        source_token=public_token,
    )
    db.commit()
    return RegistrationResult(True, "Registro exitoso", customer, purchase, attempt)


def set_purchase_status(db: Session, purchase_id: int, status: str, actor_email: str | None) -> Purchase:
    purchase = db.get(Purchase, purchase_id)
    if purchase is None:
        raise NotFoundError("Compra no encontrada")
    if status not in {"pending", "approved", "rejected"}:
        raise ValueError("Estado invalido")
    before = {
        "status": purchase.status,
        "customer_id": purchase.customer_id,
        "purchase_date": purchase.purchase_date,
    }
    purchase.status = status
    write_audit(
        db,
        actor_email=actor_email,
        action="set_purchase_status",
        entity_type="purchase",
        entity_id=str(purchase.id),
        before=before,
        after={"status": purchase.status},
    )
    db.commit()
    db.refresh(purchase)
    return purchase


def approve_purchase(db: Session, purchase_id: int, actor_email: str | None) -> Purchase:
    return set_purchase_status(db, purchase_id, "approved", actor_email)


def reject_purchase(db: Session, purchase_id: int, actor_email: str | None) -> Purchase:
    return set_purchase_status(db, purchase_id, "rejected", actor_email)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _jsonify_row(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=UTC)


def customer_summary_subquery() -> Select[tuple[Any, ...]]:
    latest_approved = func.max(case((Purchase.status == "approved", Purchase.purchase_date), else_=None)).label("latest_purchase_date")
    total = func.count(Purchase.id).label("total_purchases")
    pending = func.sum(case((Purchase.status == "pending", 1), else_=0)).label("pending_purchases")
    approved = func.sum(case((Purchase.status == "approved", 1), else_=0)).label("approved_purchases")
    rejected = func.sum(case((Purchase.status == "rejected", 1), else_=0)).label("rejected_purchases")
    failed = func.sum(case((Purchase.status == "failed", 1), else_=0)).label("failed_purchases")
    return (
        select(
            Customer.id.label("id"),
            Customer.first_name.label("first_name"),
            Customer.last_name.label("last_name"),
            Customer.phone.label("phone"),
            Customer.email.label("email"),
            Customer.tier.label("tier"),
            latest_approved,
            total,
            pending,
            approved,
            rejected,
            failed,
        )
        .select_from(Customer)
        .outerjoin(Purchase, Purchase.customer_id == Customer.id)
        .group_by(Customer.id)
    ).subquery()


def list_customers(
    db: Session,
    *,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    tier: str | None = None,
    exact_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    inactive_since: date | None = None,
    purchase_status: str | None = None,
) -> list[dict[str, Any]]:
    summary = customer_summary_subquery()
    q = select(summary)

    if name:
        like = f"%{name.strip().lower()}%"
        q = q.where(or_(func.lower(summary.c.first_name).like(like), func.lower(summary.c.last_name).like(like)))
    if phone:
        q = q.where(summary.c.phone.ilike(f"%{normalize_phone(phone) or phone}%"))
    if email:
        q = q.where(func.lower(summary.c.email).like(f"%{normalize_email(email) or email.lower()}%"))
    if tier:
        q = q.where(summary.c.tier == normalize_customer_tier(tier))
    if inactive_since:
        cutoff = start_of_day(inactive_since)
        q = q.where(or_(summary.c.latest_purchase_date.is_(None), summary.c.latest_purchase_date < cutoff))
    if exact_date or date_from or date_to or purchase_status:
        purchase_filters = select(Purchase.customer_id)
        conditions = []
        if exact_date:
            conditions.append(Purchase.purchase_date >= start_of_day(exact_date))
            conditions.append(Purchase.purchase_date <= end_of_day(exact_date))
        if date_from:
            conditions.append(Purchase.purchase_date >= start_of_day(date_from))
        if date_to:
            conditions.append(Purchase.purchase_date <= end_of_day(date_to))
        if purchase_status:
            conditions.append(Purchase.status == purchase_status)
        for condition in conditions:
            purchase_filters = purchase_filters.where(condition)
        q = q.where(summary.c.id.in_(purchase_filters.distinct()))

    q = q.order_by(summary.c.last_name.asc(), summary.c.first_name.asc(), summary.c.id.desc())
    rows = db.execute(q).mappings().all()
    return [_jsonify_row(dict(row)) for row in rows]


def list_purchases(
    db: Session,
    *,
    customer_id: int | None = None,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    tier: str | None = None,
    max_amount: int | None = None,
    exact_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    purchase_status: str | None = None,
    inactive_since: date | None = None,
) -> list[dict[str, Any]]:
    q = select(
        Purchase.id,
        Purchase.customer_id,
        Customer.first_name,
        Customer.last_name,
        Customer.phone,
        Customer.email,
        Customer.tier,
        Purchase.purchase_date,
        Purchase.status,
        Purchase.source_token,
        Purchase.description,
        Purchase.amount,
    ).select_from(Purchase).outerjoin(Customer, Customer.id == Purchase.customer_id)

    if customer_id is not None:
        q = q.where(Purchase.customer_id == customer_id)
    if name:
        like = f"%{name.strip().lower()}%"
        q = q.where(or_(func.lower(Customer.first_name).like(like), func.lower(Customer.last_name).like(like)))
    if phone:
        q = q.where(Customer.phone.ilike(f"%{normalize_phone(phone) or phone}%"))
    if email:
        q = q.where(func.lower(Customer.email).like(f"%{normalize_email(email) or email.lower()}%"))
    if tier:
        q = q.where(Customer.tier == normalize_customer_tier(tier))
    if max_amount is not None:
        q = q.where(Purchase.amount.is_not(None), Purchase.amount <= max_amount)
    if exact_date:
        q = q.where(Purchase.purchase_date >= start_of_day(exact_date), Purchase.purchase_date <= end_of_day(exact_date))
    if date_from:
        q = q.where(Purchase.purchase_date >= start_of_day(date_from))
    if date_to:
        q = q.where(Purchase.purchase_date <= end_of_day(date_to))
    if purchase_status:
        q = q.where(Purchase.status == purchase_status)
    if inactive_since:
        cutoff = start_of_day(inactive_since)
        latest = (
            select(Purchase.customer_id, func.max(Purchase.purchase_date).label("latest_approved"))
            .where(Purchase.status == "approved")
            .group_by(Purchase.customer_id)
            .subquery()
        )
        q = q.outerjoin(latest, latest.c.customer_id == Customer.id).where(or_(latest.c.latest_approved.is_(None), latest.c.latest_approved < cutoff))

    q = q.order_by(Purchase.purchase_date.desc(), Purchase.id.desc())
    rows = db.execute(q).mappings().all()
    return [_jsonify_row(dict(row)) for row in rows]


def compute_stats(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    attempts = select(RegistrationAttempt)
    purchases = select(Purchase)
    if date_from:
        attempts = attempts.where(RegistrationAttempt.created_at >= start_of_day(date_from))
        purchases = purchases.where(Purchase.purchase_date >= start_of_day(date_from))
    if date_to:
        attempts = attempts.where(RegistrationAttempt.created_at <= end_of_day(date_to))
        purchases = purchases.where(Purchase.purchase_date <= end_of_day(date_to))

    attempt_rows = db.execute(attempts).scalars().all()
    purchase_rows = db.execute(purchases).scalars().all()

    total_interactions = len(attempt_rows)
    success_interactions = sum(1 for item in attempt_rows if item.status == "success")
    failed_interactions = sum(1 for item in attempt_rows if item.status == "failure")

    total_purchases = len(purchase_rows)
    pending_purchases = sum(1 for item in purchase_rows if item.status == "pending")
    approved_purchases = sum(1 for item in purchase_rows if item.status == "approved")
    rejected_purchases = sum(1 for item in purchase_rows if item.status == "rejected")
    failed_purchases = sum(1 for item in purchase_rows if item.status == "failed")

    unique_customers = len({item.customer_id for item in purchase_rows if item.customer_id is not None})
    active_customers = len({item.customer_id for item in purchase_rows if item.customer_id is not None and item.status == "approved"})
    total_customers = db.scalar(select(func.count()).select_from(Customer)) or 0
    inactive_customers = max(0, int(total_customers) - active_customers)
    conversion_rate = (approved_purchases / total_interactions) if total_interactions else 0.0

    return {
        "total_interactions": total_interactions,
        "success_interactions": success_interactions,
        "failed_interactions": failed_interactions,
        "total_purchases": total_purchases,
        "pending_purchases": pending_purchases,
        "approved_purchases": approved_purchases,
        "rejected_purchases": rejected_purchases,
        "failed_purchases": failed_purchases,
        "unique_customers": unique_customers,
        "active_customers": active_customers,
        "inactive_customers": inactive_customers,
        "conversion_rate": round(conversion_rate, 4),
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
    }


def daily_activity(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    attempts = select(RegistrationAttempt)
    purchases = select(Purchase)
    if date_from:
        attempts = attempts.where(RegistrationAttempt.created_at >= start_of_day(date_from))
        purchases = purchases.where(Purchase.purchase_date >= start_of_day(date_from))
    if date_to:
        attempts = attempts.where(RegistrationAttempt.created_at <= end_of_day(date_to))
        purchases = purchases.where(Purchase.purchase_date <= end_of_day(date_to))

    attempt_rows = db.execute(attempts).scalars().all()
    purchase_rows = db.execute(purchases).scalars().all()

    aggregated: dict[str, dict[str, Any]] = {}

    for attempt in attempt_rows:
        day = attempt.created_at.astimezone().date().isoformat()
        item = aggregated.setdefault(day, {"day": day, "attempts": 0, "purchases": 0, "approved": 0, "rejected": 0, "failed": 0, "pending": 0})
        item["attempts"] += 1

    for purchase in purchase_rows:
        day = purchase.purchase_date.astimezone().date().isoformat()
        item = aggregated.setdefault(day, {"day": day, "attempts": 0, "purchases": 0, "approved": 0, "rejected": 0, "failed": 0, "pending": 0})
        item["purchases"] += 1
        if purchase.status == "approved":
            item["approved"] += 1
        elif purchase.status == "rejected":
            item["rejected"] += 1
        elif purchase.status == "failed":
            item["failed"] += 1
        elif purchase.status == "pending":
            item["pending"] += 1

    return [aggregated[key] for key in sorted(aggregated)]
