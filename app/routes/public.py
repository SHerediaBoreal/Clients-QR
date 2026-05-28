from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.schemas import PublicRegisterPayload
from app.services import register_public_purchase
from app.web import page

router = APIRouter(tags=["public"])


def _public_context(request: Request) -> dict[str, str | None]:
    identity = request.session.get("public_identity") or {}
    return {
        "first_name": identity.get("first_name"),
        "last_name": identity.get("last_name"),
        "email": identity.get("email"),
        "google_sub": identity.get("sub"),
    }


def _public_registration_failure(public_token: str, message: str) -> RedirectResponse:
    query = urlencode({"status": "failure", "message": message})
    return RedirectResponse(url=f"/r/{escape(public_token)}/result?{query}", status_code=303)


def _public_registration_error_message(error: ValidationError) -> str:
    messages: list[str] = []
    for item in error.errors():
        field = item.get("loc", [None])[0]
        if field == "email":
            messages.append("El mail ingresado no es válido.")
        elif field == "phone":
            messages.append(str(item.get("msg") or "El teléfono ingresado no es válido."))
    return " ".join(messages) or "Revisá el mail y el teléfono ingresados."


@router.get("/r/{public_token}", response_class=HTMLResponse)
async def public_register_page(request: Request, public_token: str):
    identity = _public_context(request)
    body = f"""
    <div class="public-center">
      <div class="notice">
        Escaneá, completá los datos y sumate a Suplementos Yerba Buena
      </div>
      <div class="card">
        <h2>Registro</h2>
        <form method="post" action="/api/public/register">
          <input type="hidden" name="public_token" value="{escape(public_token)}" />
          <div class="filters" style="grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));">
            <input class="input" name="first_name" placeholder="Nombre" value="{escape(identity.get('first_name') or '')}" required />
            <input class="input" name="last_name" placeholder="Apellido" value="{escape(identity.get('last_name') or '')}" required />
            <input class="input" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="Teléfono" required />
            <input class="input" name="email" type="email" autocomplete="email" placeholder="Mail (opcional)" value="{escape(identity.get('email') or '')}" />
          </div>
          <div class="actions" style="margin-top:1rem;">
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
    default_message = "La compra quedó registrada correctamente." if success else "No se pudo registrar la compra."
    body = f"""
    <div class="notice {body_class}">
      <strong>{escape(title)}.</strong> {escape(message or default_message)}
    </div>
    <p>{badge}</p>
    <p><a class="btn" href="/r/{escape(public_token)}">Volver</a></p>
    """
    return page(title, body, subtitle="Respuesta final para el cliente")


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
        google_sub=payload.google_sub or (request.session.get("public_identity") or {}).get("sub"),
        public_token=payload.public_token or public_token,
        request_ip=ip,
        user_agent=user_agent,
    )
    message = "La compra fue registrada y quedó pendiente de revisión."
    if not result.success:
        message = "No fue posible registrar la compra."
    query = urlencode({"status": "success" if result.success else "failure", "message": message})
    return RedirectResponse(url=f"/r/{escape(public_token)}/result?{query}", status_code=303)


@router.post("/api/public/purchase-intent")
async def public_purchase_intent(request: Request, db: Session = Depends(get_db)):
    try:
        payload = PublicRegisterPayload.model_validate(await request.json())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Payload inválido") from exc

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    result = register_public_purchase(
        db,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        email=str(payload.email) if payload.email else None,
        google_sub=payload.google_sub,
        public_token=payload.public_token or settings.public_token,
        request_ip=ip,
        user_agent=user_agent,
    )
    return JSONResponse(
        {
            "status": "success" if result.success else "failure",
            "message": result.message,
            "purchase_id": result.purchase.id if result.purchase else None,
            "customer_id": result.customer.id if result.customer else None,
        }
    )
