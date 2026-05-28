from __future__ import annotations

import json
import secrets
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.services import admin_is_allowed, admin_local_login_allowed
from app.web import page

router = APIRouter(tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _google_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _ensure_google_oauth() -> None:
    if not _google_configured():
        raise HTTPException(status_code=503, detail="Google OAuth no está configurado")


def _redirect_uri(request: Request, callback_name: str) -> str:
    return str(request.url_for(callback_name))


def _authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def _exchange_code(code: str, redirect_uri: str) -> dict[str, str]:
    payload = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
        data = json.loads(response.read().decode("utf-8"))
    if "access_token" not in data:
        raise HTTPException(status_code=401, detail="No fue posible autenticar con Google")
    return data


def _fetch_userinfo(access_token: str) -> dict[str, object]:
    request = urllib.request.Request(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


@router.get("/auth/admin/google/login")
async def admin_google_login(request: Request):
    _ensure_google_oauth()
    state = secrets.token_urlsafe(32)
    request.session["admin_oauth_state"] = state
    return RedirectResponse(
        url=_authorize_url(
            client_id=settings.google_client_id,
            redirect_uri=_redirect_uri(request, "admin_google_callback"),
            state=state,
        ),
        status_code=303,
    )


@router.get("/auth/admin/google/callback", name="admin_google_callback")
async def admin_google_callback(request: Request, db: Session = Depends(get_db), code: str | None = None, state: str | None = None):
    _ensure_google_oauth()
    expected_state = request.session.pop("admin_oauth_state", None)
    if not code or not state or state != expected_state:
        raise HTTPException(status_code=401, detail="Estado OAuth inválido")

    token_data = _exchange_code(code, _redirect_uri(request, "admin_google_callback"))
    profile = _fetch_userinfo(token_data["access_token"])
    email = str(profile.get("email") or "").strip().lower()
    if not email or not admin_is_allowed(db, email):
        request.session.clear()
        body = """
        <div class="notice failure">
          <strong>Acceso denegado.</strong> El correo autenticado no está habilitado para administrar el sistema.
        </div>
        <p><a class="btn" href="/admin/login">Volver al login</a></p>
        """
        return page("Acceso denegado", body, subtitle="Google autenticó la identidad, pero el email no está en la allowlist.")

    request.session["admin_email"] = email
    request.session["admin_name"] = profile.get("name")
    request.session["admin_auth_method"] = "google"
    return RedirectResponse(url="/admin", status_code=303)


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request):
    google_block = """
    <div class="notice">
      Ingresá con la cuenta autorizada para acceder al panel.
    </div>
    <p><a class="btn" href="/auth/admin/google/login">Ingresar con Google</a></p>
    """ if _google_configured() else """
    <div class="notice failure">
      Google OAuth no está configurado. Definí <code>GOOGLE_CLIENT_ID</code> y <code>GOOGLE_CLIENT_SECRET</code>.
    </div>
    """

    local_block = """
    <div class="card" style="margin-top:1rem;">
      <h2>Ingresar con mail y teléfono</h2>
      <p class="small">El mail funciona como usuario y el teléfono como contraseña.</p>
      <form method="post" action="/auth/admin/local/login">
        <div class="filters" style="grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));">
          <input class="input" name="email" type="email" placeholder="Mail" required />
          <input class="input" name="phone" type="tel" placeholder="Teléfono" required />
        </div>
        <div class="actions" style="margin-top:1rem;">
          <button class="btn" type="submit">Ingresar con mail y teléfono</button>
        </div>
      </form>
    </div>
    """

    if not settings.has_local_admin_accounts:
        local_block += """
        <div class="notice failure" style="margin-top:1rem;">
          No hay credenciales locales configuradas. Definí <code>ADMIN_LOCAL_ACCOUNTS</code> en el archivo `.env`.
        </div>
        """

    body = f"""
    {google_block}
    {local_block}
    """
    return page("Login admin", body, subtitle="Acceso restringido por Google o credenciales locales")


@router.post("/auth/admin/local/login")
async def admin_local_login(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    phone: str = Form(...),
):
    if not settings.has_local_admin_accounts:
        raise HTTPException(status_code=503, detail="No hay credenciales locales configuradas")

    if not admin_local_login_allowed(db, email, phone):
        body = """
        <div class="notice failure">
          <strong>Acceso denegado.</strong> Las credenciales ingresadas no coinciden con un usuario permitido.
        </div>
        <p><a class="btn" href="/admin/login">Volver al login</a></p>
        """
        return page("Acceso denegado", body, subtitle="Credenciales locales inválidas")

    request.session["admin_email"] = email.strip().lower()
    request.session["admin_name"] = email.strip().lower()
    request.session["admin_auth_method"] = "local"
    return RedirectResponse(url="/admin", status_code=303)


@router.get("/auth/public/google/login")
async def public_google_login(request: Request, next: str | None = None):
    _ensure_google_oauth()
    state = secrets.token_urlsafe(32)
    request.session["public_oauth_state"] = state
    if next:
        request.session["public_next"] = next
    return RedirectResponse(
        url=_authorize_url(
            client_id=settings.google_client_id,
            redirect_uri=_redirect_uri(request, "public_google_callback"),
            state=state,
        ),
        status_code=303,
    )


@router.get("/auth/public/google/callback", name="public_google_callback")
async def public_google_callback(request: Request, code: str | None = None, state: str | None = None):
    _ensure_google_oauth()
    expected_state = request.session.pop("public_oauth_state", None)
    if not code or not state or state != expected_state:
        raise HTTPException(status_code=401, detail="Estado OAuth inválido")

    token_data = _exchange_code(code, _redirect_uri(request, "public_google_callback"))
    profile = _fetch_userinfo(token_data["access_token"])
    request.session["public_identity"] = {
        "provider": "google",
        "sub": profile.get("sub"),
        "email": profile.get("email"),
        "first_name": profile.get("given_name"),
        "last_name": profile.get("family_name"),
        "name": profile.get("name"),
        "verified_email": profile.get("email_verified", False),
    }
    redirect_to = request.session.pop("public_next", "/")
    return RedirectResponse(url=redirect_to, status_code=303)


@router.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.pop("admin_email", None)
    request.session.pop("admin_name", None)
    request.session.pop("admin_auth_method", None)
    return RedirectResponse(url="/admin/login", status_code=303)
