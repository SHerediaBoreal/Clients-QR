from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import PublicRegisterPayload
from app.services import register_public_purchase
from app.web import page

router = APIRouter(tags=["public"])


def _public_registration_failure(public_token: str, message: str) -> RedirectResponse:
    query = urlencode({"status": "failure", "message": message})
    return RedirectResponse(url=f"/r/{escape(public_token)}/result?{query}", status_code=303)


def _public_registration_error_message(error: ValidationError) -> str:
    messages: list[str] = []
    for item in error.errors():
        field = item.get("loc", [None])[0]
        if field == "email":
            messages.append("El mail ingresado no es v\u00e1lido.")
        elif field == "phone":
            messages.append(str(item.get("msg") or "El tel\u00e9fono ingresado no es v\u00e1lido."))
    return " ".join(messages) or "Revis\u00e1 el mail y el tel\u00e9fono ingresados."


def _public_form_context(request: Request) -> dict[str, str]:
    values = {"first_name": "", "last_name": "", "email": "", "phone": ""}

    stored_values = request.session.get("public_form_values")
    if isinstance(stored_values, dict):
        for key in values:
            raw_value = stored_values.get(key)
            if raw_value is not None:
                values[key] = str(raw_value)

    identity = request.session.get("public_identity")
    if isinstance(identity, dict):
        if not values["first_name"]:
            values["first_name"] = str(identity.get("first_name") or "")
        if not values["last_name"]:
            values["last_name"] = str(identity.get("last_name") or "")
        if not values["email"]:
            values["email"] = str(identity.get("email") or "")

    return values


@router.get("/r/{public_token}", response_class=HTMLResponse)
async def public_register_page(request: Request, public_token: str):
    form_values = _public_form_context(request)
    body = f"""
    <div class="public-center">
      <div class="notice">
        Escane\u00e1, complet\u00e1 los datos y sumate a Suplementos Yerba Buena
      </div>
      <div class="card">
        <h2>Registro</h2>
        <form method="post" action="/api/public/register" autocomplete="off">
          <input type="hidden" name="public_token" value="{escape(public_token)}" />
          <div class="filters public-register-grid">
            <input class="input" name="first_name" value="{escape(form_values['first_name'])}" placeholder="Nombre" autocomplete="off" required />
            <input class="input" name="last_name" value="{escape(form_values['last_name'])}" placeholder="Apellido" autocomplete="off" required />
            <input class="input" name="email" type="email" value="{escape(form_values['email'])}" autocomplete="off" placeholder="Mail (opcional)" />
            <input class="input" name="phone" type="tel" inputmode="numeric" pattern="[0-9]*" oninput="this.value=this.value.replace(/\\D/g, '')" value="{escape(form_values['phone'])}" autocomplete="off" placeholder="Tel\u00e9fono" required />
          </div>
          <div class="actions public-register-actions">
            <button class="btn" type="submit">Registrar compra</button>
            <a class="btn" href="/auth/public/google/login?next=/r/{escape(public_token)}">Entrar con Google</a>
          </div>
        </form>
      </div>
    </div>
    """
    return page(
        "Fidelidad Suplementos YB",
        body,
        shell_class="shell shell-public",
        body_class="body-public-bg",
    )


@router.get("/r/{public_token}/result", response_class=HTMLResponse)
async def public_result_page(request: Request, public_token: str, status: str = "success", message: str | None = None):
    success = status == "success"
    badge = "success" if success else "failure"
    title = "Registro exitoso" if success else "Registro fallido"
    body_class = "success" if success else "failure"
    default_message = "La compra qued\u00f3 registrada correctamente." if success else "No se pudo registrar la compra."
    body = f"""
    <div class="notice {body_class}">
      <strong>{escape(title)}.</strong> {escape(message or default_message)}
    </div>
    <p>{badge}</p>
    <p><a class="btn" href="/r/{escape(public_token)}">Volver</a></p>
    """
    return page(
        title,
        body,
        subtitle="Respuesta final para el cliente",
        shell_class="shell shell-public shell-public-result",
        body_class="body-public-bg",
    )


@router.post("/api/public/register")
async def public_register(
    request: Request,
    db: Session = Depends(get_db),
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone: str = Form(...),
    email: str | None = Form(None),
    google_sub: str | None = Form(None),
    public_token: str = Form(...),
):
    request.session["public_form_values"] = {
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "email": email or "",
    }
    try:
        payload = PublicRegisterPayload.model_validate(
            {
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "email": email,
                "google_sub": google_sub,
                "public_token": public_token,
            }
        )
    except ValidationError as exc:
        return _public_registration_failure(public_token, _public_registration_error_message(exc))

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    result = register_public_purchase(
        db,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        email=str(payload.email) if payload.email else None,
        google_sub=payload.google_sub,
        public_token=payload.public_token or public_token,
        request_ip=ip,
        user_agent=user_agent,
    )
    message = "La compra fue registrada y qued\u00f3 pendiente de revisi\u00f3n."
    if not result.success:
        message = "No fue posible registrar la compra."
    query = urlencode({"status": "success" if result.success else "failure", "message": message})
    return RedirectResponse(url=f"/r/{escape(public_token)}/result?{query}", status_code=303)
