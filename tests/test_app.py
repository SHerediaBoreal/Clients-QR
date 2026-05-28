from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("PUBLIC_TOKEN", "qr-test")
os.environ.setdefault("ADMIN_EMAIL_ALLOWLIST", "admin@example.com")
os.environ.setdefault("ADMIN_LOCAL_ACCOUNTS", "admin@example.com:5551234")
os.environ.setdefault("APP_ENV", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Customer, Purchase, RegistrationAttempt
from app.routes.admin import require_admin
from app.web import format_date_only, format_dt
from app.services import seed_admin_users


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_admin_users(db, ["admin@example.com"], [("admin@example.com", "5551234")])


def make_customer(
    db,
    *,
    first_name: str,
    last_name: str,
    phone: str,
    email: str,
    tier: str | None = None,
) -> Customer:
    customer = Customer(first_name=first_name, last_name=last_name, phone=phone, email=email, tier=tier, status="active")
    db.add(customer)
    db.flush()
    return customer


def make_attempt(db, *, customer_id: int | None, status: str, created_at: datetime) -> RegistrationAttempt:
    attempt = RegistrationAttempt(
        customer_id=customer_id,
        status=status,
        failure_reason=None if status == "success" else "error",
        source="qr_public",
        ip_hash=None,
        user_agent_hash=None,
        created_at=created_at,
    )
    db.add(attempt)
    db.flush()
    return attempt


def make_purchase(
    db,
    *,
    customer_id: int | None,
    status: str,
    purchase_date: datetime,
    source_token: str = "qr-test",
    description: str | None = None,
    amount: int | None = None,
) -> Purchase:
    purchase = Purchase(
        customer_id=customer_id,
        status=status,
        purchase_date=purchase_date,
        source_token=source_token,
        description=description,
        amount=amount,
        notes=None,
    )
    db.add(purchase)
    db.flush()
    return purchase


def test_public_register_creates_customer_and_pending_purchase():
    reset_database()

    with TestClient(app) as client:
        page = client.get("/r/qr-test")
        assert page.status_code == 200
        assert "public-center" in page.text
        assert "body-public-bg" in page.text
        assert "Estado del flujo" not in page.text
        assert 'rel="icon"' in page.text

        response = client.post(
            "/api/public/register",
            data={
                "first_name": "Ana",
                "last_name": "Perez",
                "phone": "+54 11 1234 5678",
                "email": "ana@example.com",
                "public_token": "qr-test",
            },
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "Registro exitoso" in response.text

    with SessionLocal() as db:
        assert db.query(Customer).count() == 1
        assert db.query(Purchase).count() == 1
        purchase = db.query(Purchase).first()
        assert purchase is not None
        assert purchase.status == "pending"
        attempt = db.query(RegistrationAttempt).first()
        assert attempt is not None
        assert attempt.status == "success"


def test_public_register_allows_empty_email():
    reset_database()

    with TestClient(app) as client:
        response = client.post(
            "/api/public/register",
            data={
                "first_name": "Ana",
                "last_name": "Perez",
                "phone": "+54 11 1234 5678",
                "email": "",
                "public_token": "qr-test",
            },
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "Registro exitoso" in response.text

    with SessionLocal() as db:
        customer = db.query(Customer).first()
        assert customer is not None
        assert customer.email is None


def test_public_register_rejects_invalid_email_and_phone():
    reset_database()

    with TestClient(app) as client:
        response = client.post(
            "/api/public/register",
            data={
                "first_name": "Ana",
                "last_name": "Perez",
                "phone": "abc",
                "email": "no-es-un-mail",
                "public_token": "qr-test",
            },
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "Registro fallido" in response.text
    assert "mail ingresado no es válido" in response.text
    assert "teléfono" in response.text

    with SessionLocal() as db:
        assert db.query(Customer).count() == 0
        assert db.query(Purchase).count() == 0
        assert db.query(RegistrationAttempt).count() == 0


def test_admin_panel_is_protected_without_session():
    reset_database()

    with TestClient(app) as client:
        app.dependency_overrides.pop(require_admin, None)
        response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_login_page_has_split_layout():
    reset_database()

    with TestClient(app) as client:
        response = client.get("/admin/login")

    assert response.status_code == 200
    assert "Acceso restringido por Google o credenciales locales" in response.text
    assert "Google OAuth" in response.text or "Ingresá con la cuenta autorizada" in response.text


def test_admin_local_login_allows_panel_access():
    reset_database()

    with TestClient(app) as client:
        response = client.post(
            "/auth/admin/local/login",
            data={"email": "admin@example.com", "phone": "5551234"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/admin"

        dashboard = client.get("/admin")
        assert dashboard.status_code == 200
        assert "Filtros activos" in dashboard.text
        assert "admin-header" in dashboard.text
        assert "admin-logo" in dashboard.text
        assert 'autocomplete="off"' in dashboard.text
        assert "focusin" in dashboard.text


def test_admin_can_update_customer_tier_and_purchase_details():
    reset_database()

    with SessionLocal() as db:
        customer = make_customer(db, first_name="Ana", last_name="Perez", phone="111", email="ana@example.com")
        purchase = make_purchase(
            db,
            customer_id=customer.id,
            status="pending",
            purchase_date=datetime(2026, 5, 10, 12, tzinfo=UTC),
        )
        db.commit()

    app.dependency_overrides[require_admin] = lambda: "admin@example.com"
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/admin/customers/{customer.id}/tier",
                data={"tier": "VIP", "return_to": f"/admin/customers/{customer.id}"},
                follow_redirects=True,
            )
            assert response.status_code == 200
            assert "Tier: VIP" in response.text

            response = client.post(
                f"/api/admin/purchases/{purchase.id}/details",
                data={
                    "description": "Compra grande",
                    "amount": "1500",
                    "return_to": "/admin",
                },
                follow_redirects=True,
            )
            assert response.status_code == 200
            assert "Compra grande" in response.text
            assert "1500" in response.text
    finally:
        app.dependency_overrides.pop(require_admin, None)

    with SessionLocal() as db:
        updated_customer = db.get(Customer, customer.id)
        updated_purchase = db.get(Purchase, purchase.id)
        assert updated_customer is not None
        assert updated_customer.tier == "VIP"
        assert updated_purchase is not None
        assert updated_purchase.description == "Compra grande"
        assert updated_purchase.amount == 1500


def test_admin_dashboard_filters_by_tier_and_max_amount():
    reset_database()

    with SessionLocal() as db:
        vip_customer = make_customer(db, first_name="Ana", last_name="Perez", phone="111", email="ana@example.com", tier="VIP")
        low_customer = make_customer(db, first_name="Bruno", last_name="Diaz", phone="222", email="bruno@example.com", tier="bajo")
        make_purchase(
            db,
            customer_id=vip_customer.id,
            status="approved",
            purchase_date=datetime(2026, 5, 10, 12, tzinfo=UTC),
            description="Compra VIP",
            amount=400,
        )
        make_purchase(
            db,
            customer_id=low_customer.id,
            status="approved",
            purchase_date=datetime(2026, 5, 11, 12, tzinfo=UTC),
            description="Compra baja",
            amount=900,
        )
        db.commit()

    app.dependency_overrides[require_admin] = lambda: "admin@example.com"
    try:
        with TestClient(app) as client:
            response = client.get("/admin?tier=VIP&max_amount=500")
            assert response.status_code == 200
            assert "Ana Perez" in response.text
            assert "VIP" in response.text
            assert "Compra VIP" in response.text
            assert "400" in response.text
            assert "Bruno Diaz" not in response.text
            assert "Compra baja" not in response.text
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_admin_rejects_invalid_tier_and_amount_updates():
    reset_database()

    with SessionLocal() as db:
        customer = make_customer(db, first_name="Ana", last_name="Perez", phone="111", email="ana@example.com")
        purchase = make_purchase(db, customer_id=customer.id, status="pending", purchase_date=datetime(2026, 5, 10, 12, tzinfo=UTC))
        db.commit()

    app.dependency_overrides[require_admin] = lambda: "admin@example.com"
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/admin/customers/{customer.id}/tier",
                data={"tier": "oro", "return_to": f"/admin/customers/{customer.id}"},
                follow_redirects=False,
            )
            assert response.status_code == 400

            response = client.post(
                f"/api/admin/purchases/{purchase.id}/details",
                data={"description": "X", "amount": "-1", "return_to": "/admin"},
                follow_redirects=False,
            )
            assert response.status_code == 400
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_admin_filters_and_stats_work():
    reset_database()

    with SessionLocal() as db:
        ana = make_customer(db, first_name="Ana", last_name="Perez", phone="111", email="ana@example.com")
        bruno = make_customer(db, first_name="Bruno", last_name="Diaz", phone="222", email="bruno@example.com")
        carla = make_customer(db, first_name="Carla", last_name="Lopez", phone="333", email="carla@example.com")

        make_attempt(db, customer_id=ana.id, status="success", created_at=datetime(2026, 5, 1, 12, tzinfo=UTC))
        make_attempt(db, customer_id=bruno.id, status="failure", created_at=datetime(2026, 5, 2, 12, tzinfo=UTC))
        make_attempt(db, customer_id=carla.id, status="success", created_at=datetime(2026, 5, 3, 12, tzinfo=UTC))

        make_purchase(db, customer_id=ana.id, status="approved", purchase_date=datetime(2026, 5, 10, 12, tzinfo=UTC))
        make_purchase(db, customer_id=ana.id, status="pending", purchase_date=datetime(2026, 5, 11, 12, tzinfo=UTC))
        make_purchase(db, customer_id=bruno.id, status="rejected", purchase_date=datetime(2026, 5, 2, 12, tzinfo=UTC))
        make_purchase(db, customer_id=carla.id, status="approved", purchase_date=datetime(2026, 4, 1, 12, tzinfo=UTC))
        db.commit()

    app.dependency_overrides[require_admin] = lambda: "admin@example.com"
    try:
        with TestClient(app) as client:
            response = client.get("/api/admin/customers?q=Ana")
            assert response.status_code == 200
            data = response.json()
            assert len(data["items"]) == 1

            response = client.get("/api/admin/purchases?purchase_status=approved")
            assert response.status_code == 200
            purchases = response.json()["items"]
            assert len(purchases) == 2

            response = client.get("/api/admin/customers?inactive_since=2026-05-05")
            assert response.status_code == 200
            inactive = {item["first_name"] for item in response.json()["items"]}
            assert inactive == {"Bruno", "Carla"}

            response = client.get("/api/admin/stats?date_from=2026-05-01&date_to=2026-05-31")
            assert response.status_code == 200
            stats = response.json()
            assert stats["total_interactions"] == 3
            assert stats["success_interactions"] == 2
            assert stats["failed_interactions"] == 1
            assert stats["approved_purchases"] == 1
            assert stats["rejected_purchases"] == 1
            assert stats["pending_purchases"] == 1
            assert stats["failed_purchases"] == 0
            assert stats["unique_customers"] == 2

            with SessionLocal() as verify_db:
                pending_purchase = verify_db.query(Purchase).filter(Purchase.status == "pending").first()
                assert pending_purchase is not None
                response = client.post(
                    f"/api/admin/purchases/{pending_purchase.id}/status",
                    data={"status": "approved"},
                    follow_redirects=False,
                )
                assert response.status_code == 303
                updated = verify_db.get(Purchase, pending_purchase.id)
                assert updated is not None
                verify_db.refresh(updated)
                assert updated.status == "approved"
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_format_helpers_accept_iso_strings_from_sqlite():
    assert format_dt("2026-05-28T12:34:56+00:00") == "2026-05-28 09:34:56"
    assert format_date_only("2026-05-28T12:34:56+00:00") == "2026-05-28"
    assert format_date_only(date(2026, 5, 28)) == "2026-05-28"
