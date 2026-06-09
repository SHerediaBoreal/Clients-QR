from __future__ import annotations

import os
import sys
import base64
import json
from datetime import UTC, date, datetime, timedelta, timezone
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
from app.core.timezones import GMT_MINUS_3_TZ, end_of_day_utc, start_of_day_utc
from app.routes import auth as auth_routes
from app.routes.admin import require_admin
from app.web import format_date_only, format_dt, page
from app.services import daily_activity, list_purchases, seed_admin_users


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


def test_public_register_matches_existing_customer_case_insensitively_and_enriches_email():
    reset_database()

    with SessionLocal() as db:
        customer = make_customer(db, first_name="Pepe", last_name="Juarez", phone="1565659", email=None)
        db.commit()

    with TestClient(app) as client:
        response = client.post(
            "/api/public/register",
            data={
                "first_name": "pepe",
                "last_name": "JUAREZ",
                "phone": "1565659",
                "email": "PEPE@J.COM",
                "public_token": "qr-test",
            },
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "Registro exitoso" in response.text

    with SessionLocal() as db:
        assert db.query(Customer).count() == 1
        updated_customer = db.query(Customer).first()
        assert updated_customer is not None
        assert updated_customer.id == customer.id
        assert updated_customer.first_name == "Pepe"
        assert updated_customer.last_name == "Juarez"
        assert updated_customer.email == "pepe@j.com"

        purchases = db.query(Purchase).all()
        assert len(purchases) == 1
        assert purchases[0].customer_id == customer.id


def test_public_register_page_prefills_session_identity():
    reset_database()

    original_exchange_code = auth_routes._exchange_code
    original_fetch_userinfo = auth_routes._fetch_userinfo
    auth_routes._exchange_code = lambda code, redirect_uri: {"access_token": "fake-token"}
    auth_routes._fetch_userinfo = lambda access_token: {
        "sub": "google-sub-123",
        "email": "santiheredia2013@example.com",
        "given_name": "Santi",
        "family_name": "Heredia",
        "name": "Santi Heredia",
        "email_verified": True,
    }
    try:
        with TestClient(app) as client:
            login = client.get("/auth/public/google/login?next=/r/qr-test", follow_redirects=False)
            assert login.status_code == 303

            session_cookie = client.cookies.get("clients_qr_session")
            assert session_cookie is not None
            encoded_payload = session_cookie.split(".", 1)[0]
            payload = json.loads(base64.urlsafe_b64decode(encoded_payload.encode("ascii")).decode("utf-8"))
            state = payload["public_oauth_state"]

            callback = client.get(f"/auth/public/google/callback?code=fake-code&state={state}", follow_redirects=False)
            assert callback.status_code == 303

            register_page = client.get("/r/qr-test")
            assert register_page.status_code == 200
            assert 'value="Santi"' in register_page.text
            assert 'value="Heredia"' in register_page.text
            assert 'value="santiheredia2013@example.com"' in register_page.text
    finally:
        auth_routes._exchange_code = original_exchange_code
        auth_routes._fetch_userinfo = original_fetch_userinfo


def test_public_register_persists_form_values_between_visits():
    reset_database()

    with TestClient(app) as client:
        response = client.post(
            "/api/public/register",
            data={
                "first_name": "Ana",
                "last_name": "Perez",
                "phone": "1565659",
                "email": "ana@example.com",
                "public_token": "qr-test",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        register_page = client.get("/r/qr-test")
        assert register_page.status_code == 200
        assert 'value="Ana"' in register_page.text
        assert 'value="Perez"' in register_page.text
        assert 'value="ana@example.com"' in register_page.text
        assert 'value="1565659"' in register_page.text


def test_public_register_ignores_admin_session_data():
    reset_database()

    with TestClient(app) as client:
        login = client.post(
            "/auth/admin/local/login",
            data={"email": "admin@example.com", "phone": "5551234"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        response = client.post(
            "/api/public/register",
            data={
                "first_name": "Cliente",
                "last_name": "Real",
                "phone": "+54 11 4444 5555",
                "email": "cliente@example.com",
                "public_token": "qr-test",
            },
            follow_redirects=True,
        )

    assert response.status_code == 200

    with SessionLocal() as db:
        customer = db.query(Customer).first()
        purchase = db.query(Purchase).first()
        assert customer is not None
        assert customer.first_name == "Cliente"
        assert customer.last_name == "Real"
        assert customer.phone == "541144445555"
        assert customer.email == "cliente@example.com"
        assert purchase is not None
        assert purchase.customer_id == customer.id


def test_public_pages_use_mobile_friendly_public_shell_styles():
    reset_database()

    with TestClient(app) as client:
        register_page = client.get("/r/qr-test")
        result_page = client.get("/r/qr-test/result")

    assert register_page.status_code == 200
    assert result_page.status_code == 200

    assert "shell-public" in register_page.text
    assert "public-register-grid" in register_page.text
    assert "calc(100dvh - 2.5rem)" in register_page.text
    assert "background-attachment: scroll" in register_page.text
    assert "shell-public-result" in result_page.text
    assert "body-public-bg" in result_page.text
    assert "Respuesta final para el cliente" in result_page.text


def test_public_register_phone_input_allows_only_digits_in_browser():
    reset_database()

    with TestClient(app) as client:
        register_page = client.get("/r/qr-test")

    assert register_page.status_code == 200
    assert 'name="phone"' in register_page.text
    assert 'type="tel"' in register_page.text
    assert 'inputmode="numeric"' in register_page.text
    assert 'pattern="[0-9]*"' in register_page.text
    assert "this.value=this.value.replace(/\\D/g, '')" in register_page.text


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
        assert dashboard.text.count('<button class="section-toggle" type="button" data-toggle-section') == 3
        assert dashboard.text.count('class="section-body" hidden') == 2
        assert dashboard.text.count('class="table-scroll-container') == 2
        assert "activity-section" in dashboard.text
        assert "customers-section" in dashboard.text
        assert "purchases-section" in dashboard.text
        assert "purchases-scrollbar-top" in dashboard.text
        assert "purchases-scrollbar-bottom" in dashboard.text
        assert dashboard.text.index("Acciones") < dashboard.text.index("Mail (opcional)")
        assert "max-height: calc(5 * 3.6rem + 3.25rem);" in dashboard.text
        assert "overflow-y: auto;" in dashboard.text
        assert "position: sticky;" in dashboard.text
        assert "clients_qr_admin_dashboard_state:" in dashboard.text
        assert "history.scrollRestoration = \"manual\"" in dashboard.text
        assert "sessionStorage" in dashboard.text


def test_admin_purchase_actions_respect_return_to():
    reset_database()

    with SessionLocal() as db:
        customer = make_customer(db, first_name="Ana", last_name="Perez", phone="111", email="ana@example.com")
        details_purchase = make_purchase(db, customer_id=customer.id, status="pending", purchase_date=datetime(2026, 5, 10, 12, tzinfo=UTC))
        approve_purchase_item = make_purchase(db, customer_id=customer.id, status="pending", purchase_date=datetime(2026, 5, 11, 12, tzinfo=UTC))
        reject_purchase_item = make_purchase(db, customer_id=customer.id, status="pending", purchase_date=datetime(2026, 5, 12, 12, tzinfo=UTC))
        status_purchase_item = make_purchase(db, customer_id=customer.id, status="pending", purchase_date=datetime(2026, 5, 13, 12, tzinfo=UTC))
        db.commit()

    app.dependency_overrides[require_admin] = lambda: "admin@example.com"
    return_to = "/admin?view=expanded&section=purchases"
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/admin/purchases/{details_purchase.id}/details",
                data={"description": "Compra grande", "amount": "1500", "return_to": return_to},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == return_to

            response = client.post(
                f"/api/admin/purchases/{approve_purchase_item.id}/approve",
                data={"return_to": return_to},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == return_to

            response = client.post(
                f"/api/admin/purchases/{reject_purchase_item.id}/reject",
                data={"return_to": return_to},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == return_to

            response = client.post(
                f"/api/admin/purchases/{status_purchase_item.id}/status",
                data={"status": "approved", "return_to": return_to},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == return_to
    finally:
        app.dependency_overrides.pop(require_admin, None)


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


def test_admin_dashboard_filters_and_stats_work():
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
            response = client.get("/admin?q=Ana&date_from=2026-05-01&date_to=2026-05-31")
            assert response.status_code == 200
            assert "Panel de administracion" in response.text
            assert "Interacciones" in response.text
            assert "Compras" in response.text
            assert "Ana Perez" in response.text
            assert "Bruno Diaz" not in response.text

            assert client.get("/api/admin/purchases?purchase_status=approved").status_code == 404
            assert client.get("/api/admin/stats?date_from=2026-05-01&date_to=2026-05-31").status_code == 404
            assert client.post("/api/public/purchase-intent", json={"first_name": "Ana"}).status_code == 404

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


def test_daily_activity_uses_buenos_aires_dates_and_exact_date():
    reset_database()

    with SessionLocal() as db:
        customer = make_customer(db, first_name="Ana", last_name="Perez", phone="111", email="ana@example.com")
        make_attempt(db, customer_id=customer.id, status="success", created_at=datetime(2026, 5, 9, 15, tzinfo=GMT_MINUS_3_TZ))
        make_purchase(db, customer_id=customer.id, status="approved", purchase_date=datetime(2026, 5, 9, 15, tzinfo=GMT_MINUS_3_TZ))
        make_attempt(db, customer_id=customer.id, status="success", created_at=datetime(2026, 5, 10, 15, tzinfo=GMT_MINUS_3_TZ))
        make_purchase(db, customer_id=customer.id, status="pending", purchase_date=datetime(2026, 5, 10, 15, tzinfo=GMT_MINUS_3_TZ))
        db.commit()

        exact_activity = daily_activity(db, exact_date=date(2026, 5, 9))
        assert exact_activity == [
            {
                "day": "2026-05-09",
                "attempts": 1,
                "purchases": 1,
                "approved": 1,
                "rejected": 0,
                "failed": 0,
                "pending": 0,
            }
        ]

        range_activity = daily_activity(db, date_from=date(2026, 5, 10), date_to=date(2026, 5, 10))
        assert range_activity == [
            {
                "day": "2026-05-10",
                "attempts": 1,
                "purchases": 1,
                "approved": 0,
                "rejected": 0,
                "failed": 0,
                "pending": 1,
            }
        ]


def test_purchases_are_sorted_by_id_descending():
    reset_database()

    with SessionLocal() as db:
        customer = make_customer(db, first_name="Ana", last_name="Perez", phone="111", email="ana@example.com")
        first = make_purchase(db, customer_id=customer.id, status="pending", purchase_date=datetime(2026, 5, 10, 12, tzinfo=UTC))
        second = make_purchase(db, customer_id=customer.id, status="approved", purchase_date=datetime(2026, 5, 11, 12, tzinfo=UTC))
        third = make_purchase(db, customer_id=customer.id, status="rejected", purchase_date=datetime(2026, 5, 12, 12, tzinfo=UTC))
        db.commit()

        purchases = list_purchases(db)
        assert [item["id"] for item in purchases] == [third.id, second.id, first.id]


def test_daily_activity_is_sorted_from_newest_to_oldest():
    reset_database()

    with SessionLocal() as db:
        customer = make_customer(db, first_name="Ana", last_name="Perez", phone="111", email="ana@example.com")
        make_attempt(db, customer_id=customer.id, status="success", created_at=datetime(2026, 5, 9, 12, tzinfo=UTC))
        make_purchase(db, customer_id=customer.id, status="approved", purchase_date=datetime(2026, 5, 9, 12, tzinfo=UTC))
        make_attempt(db, customer_id=customer.id, status="success", created_at=datetime(2026, 5, 10, 12, tzinfo=UTC))
        make_purchase(db, customer_id=customer.id, status="pending", purchase_date=datetime(2026, 5, 10, 12, tzinfo=UTC))
        db.commit()

        activity = daily_activity(db)
        assert [item["day"] for item in activity] == ["2026-05-10", "2026-05-09"]


def test_format_helpers_accept_iso_strings_from_sqlite():
    assert format_dt("2026-05-28T12:34:56+00:00") == "2026-05-28 09:34:56"
    assert format_dt(datetime(2026, 5, 28, 15, 26)) == "2026-05-28 15:26:00"
    assert format_dt(datetime(2026, 5, 28, 12, 34, 56, tzinfo=timezone(timedelta(hours=1)))) == "2026-05-28 08:34:56"
    assert format_date_only("2026-05-28T12:34:56+00:00") == "2026-05-28"
    assert format_date_only(date(2026, 5, 28)) == "2026-05-28"


def test_page_includes_global_frontend_error_handlers():
    response = page("Demo", "<p>Contenido</p>")

    assert response.status_code == 200
    assert 'id="frontend-error-banner"' in response.body.decode("utf-8")
    assert "window.onerror" in response.body.decode("utf-8")
    assert "window.onunhandledrejection" in response.body.decode("utf-8")
    assert "reportUnexpectedError" in response.body.decode("utf-8")


def test_gmt_minus_three_is_fixed_and_daily_boundaries_use_it():
    assert GMT_MINUS_3_TZ.utcoffset(None) == timedelta(hours=-3)
    assert GMT_MINUS_3_TZ.tzname(None) == "GMT-3"
    assert start_of_day_utc(date(2026, 5, 10)) == datetime(2026, 5, 10, 3, tzinfo=UTC)
    assert end_of_day_utc(date(2026, 5, 10)) == datetime(2026, 5, 11, 2, 59, 59, 999999, tzinfo=UTC)
