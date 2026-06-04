from __future__ import annotations

import base64
from functools import lru_cache
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import normalize_email
from app.db import get_db
from app.services import (
    CUSTOMER_TIERS,
    NotFoundError,
    approve_purchase,
    compute_stats,
    daily_activity,
    list_customers,
    list_purchases,
    parse_date,
    parse_optional_non_negative_int,
    reject_purchase,
    update_customer_tier,
    update_purchase_details,
    set_purchase_status,
    normalize_customer_tier,
)
from app.web import SafeHTML, card_grid, format_date_only, format_dt, page, status_badge, table

router = APIRouter(tags=["admin"])


def require_admin(request: Request) -> str:
    email = normalize_email(request.session.get("admin_email"))
    if not email:
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return email


def purchase_status_actions(purchase_id: int, current_status: str | None, return_to: str) -> SafeHTML:
    current = (current_status or "").strip().lower()
    buttons = []
    for status, label in (("approved", "Aprobada"), ("rejected", "Rechazada"), ("pending", "Pendiente")):
        disabled = "disabled" if current == status else ""
        buttons.append(
            f"""
            <form method="post" action="/api/admin/purchases/{purchase_id}/status">
              <input type="hidden" name="status" value="{status}" />
              <input type="hidden" name="return_to" value="{escape(return_to)}" />
              <button class="action-btn {status}" type="submit" {disabled}>{label}</button>
            </form>
            """
        )
    return SafeHTML('<div class="row-actions">' + "".join(buttons) + "</div>")


def _admin_return_path(request: Request, fallback: str = "/admin") -> str:
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    if not path.startswith("/admin"):
        return fallback
    return path


def _safe_redirect_path(value: str | None, fallback: str = "/admin") -> str:
    if not value:
        return fallback
    candidate = value.strip()
    if not candidate.startswith("/admin"):
        return fallback
    if "://" in candidate or candidate.startswith("//"):
        return fallback
    return candidate


def _customer_tier_select(current: str | None) -> str:
    options = ['<option value="">Sin tier</option>']
    for tier in CUSTOMER_TIERS:
        selected = "selected" if current == tier else ""
        options.append(f'<option value="{tier}" {selected}>{tier}</option>')
    return "".join(options)


def _purchase_amount_display(value: int | None) -> str:
    return "-" if value is None else str(value)


def purchase_amount_form(
    purchase_id: int,
    *,
    description: str | None,
    amount: int | None,
    return_to: str,
) -> SafeHTML:
    return SafeHTML(
        f"""
        <form method="post" action="/api/admin/purchases/{purchase_id}/details" class="stack" style="min-width:120px;gap:0.35rem;">
          <input type="hidden" name="return_to" value="{escape(return_to)}" />
          <input type="hidden" name="description" value="{escape(description or '')}" />
          <input class="input" name="amount" type="number" min="0" step="1" placeholder="Monto" value="{escape(str(amount) if amount is not None else '')}" style="padding:0.45rem 0.55rem;" />
          <button class="action-btn" type="submit">Guardar</button>
        </form>
        """
    )


def purchase_description_popup(
    purchase_id: int,
    *,
    description: str | None,
    amount: int | None,
    return_to: str,
) -> SafeHTML:
    dialog_id = f"purchase-desc-{purchase_id}"
    current_amount = escape(str(amount) if amount is not None else "")
    return SafeHTML(
        f"""
        <button class="action-btn" type="button" data-open-dialog="{dialog_id}">Editar descripción</button>
        <dialog id="{dialog_id}" class="mini-dialog">
          <form method="post" action="/api/admin/purchases/{purchase_id}/details" class="stack" style="gap:0.55rem;min-width:280px;">
            <strong style="font-size:1rem;">Editar descripción</strong>
            <input type="hidden" name="return_to" value="{escape(return_to)}" />
            <input type="hidden" name="amount" value="{current_amount}" />
            <textarea class="input" name="description" rows="3" placeholder="Descripcion">{escape(description or '')}</textarea>
            <div class="actions" style="justify-content:flex-end;">
              <button class="action-btn" type="button" data-close-dialog>Cancelar</button>
              <button class="action-btn approved" type="submit">Guardar</button>
            </div>
          </form>
        </dialog>
        """
    )


def customer_tier_form(
    customer_id: int,
    *,
    tier: str | None,
    return_to: str,
) -> SafeHTML:
    return SafeHTML(
        f"""
        <form method="post" action="/api/admin/customers/{customer_id}/tier" class="stack" style="align-items:flex-start;gap:0.4rem;max-width:260px;">
          <input type="hidden" name="return_to" value="{escape(return_to)}" />
          <select class="input" name="tier">
            {_customer_tier_select(tier)}
          </select>
          <button class="action-btn" type="submit">Guardar tier</button>
        </form>
        """
    )


@lru_cache(maxsize=1)
def admin_logo_data_uri() -> str:
    logo_path = Path(__file__).resolve().parent.parent / "utlis" / "pagina_4.png"
    return "data:image/png;base64," + base64.b64encode(logo_path.read_bytes()).decode("ascii")


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin_email: str = Depends(require_admin),
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    phone: str | None = Query(None),
    email: str | None = Query(None),
    tier: str | None = Query(None),
    max_amount: str | None = Query(None),
    exact_date: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    inactive_since: str | None = Query(None),
    purchase_status: str | None = Query(None),
):
    _ = request, admin_email
    exact = parse_date(exact_date)
    start = parse_date(date_from)
    end = parse_date(date_to)
    inactive = parse_date(inactive_since)
    try:
        normalized_tier = normalize_customer_tier(tier)
        max_amount_value = parse_optional_non_negative_int(max_amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    customers = list_customers(
        db,
        name=q,
        phone=phone,
        email=email,
        tier=normalized_tier,
        exact_date=exact,
        date_from=start,
        date_to=end,
        inactive_since=inactive,
        purchase_status=purchase_status,
    )
    purchases = list_purchases(
        db,
        name=q,
        phone=phone,
        email=email,
        tier=normalized_tier,
        max_amount=max_amount_value,
        exact_date=exact,
        date_from=start,
        date_to=end,
        inactive_since=inactive,
        purchase_status=purchase_status,
    )
    stats = compute_stats(db, exact_date=exact, date_from=start, date_to=end)
    daily = daily_activity(db, exact_date=exact, date_from=start, date_to=end)
    return_to = _admin_return_path(request)
    header_html = f"""
    <div class="admin-header">
      <div class="admin-header-left">
        <h1 class="admin-header-title">Panel de administracion</h1>
        <p class="admin-header-subtitle">Filtros operativos y trazabilidad</p>
      </div>
      <div class="admin-header-center">
        <img class="admin-logo" src="{admin_logo_data_uri()}" alt="Suplementos yb logo" />
      </div>
      <div class="admin-header-right">
        <form method="post" action="/admin/logout">
          <button class="btn" type="submit">Salir</button>
        </form>
      </div>
    </div>
    """

    summary_items = [
        ("Nombre", q),
        ("Teléfono", phone),
        ("Mail", email),
        ("Tier", tier),
        ("Monto max.", max_amount),
        ("Fecha exacta", exact_date),
        ("Desde", date_from),
        ("Hasta", date_to),
        ("Inactivos desde", inactive_since),
        ("Estado", purchase_status),
    ]
    filters_summary = "".join(
        f'<span class="filter-chip"><span class="filter-chip-label">{escape(label)}:</span><span class="filter-chip-value">{escape(value) if value else "-"}</span></span>'
        for label, value in summary_items
    )

    cards = card_grid(
        [
            ("Interacciones", str(stats["total_interactions"])),
            ("Exitosas", str(stats["success_interactions"])),
            ("Fallidas", str(stats["failed_interactions"])),
            ("Compras", str(stats["total_purchases"])),
            ("Aprobadas", str(stats["approved_purchases"])),
            ("Rechazadas", str(stats["rejected_purchases"])),
            ("Pendientes", str(stats["pending_purchases"])),
            ("Fallidas compra", str(stats["failed_purchases"])),
            ("Clientes unicos", str(stats["unique_customers"])),
            ("Conversion", f'{stats["conversion_rate"] * 100:.2f}%'),
        ]
    )

    filter_form = f"""
    <form class="filters" method="get" action="/admin">
      <div class="filter-group">
        <div class="filter-group-title">Filtros generales</div>
        <input class="input" name="q" placeholder="Nombre y/o apellido" value="{escape(q or '')}" autocomplete="off" />
        <input class="input" name="phone" placeholder="Numero de telefono" value="{escape(phone or '')}" autocomplete="off" />
        <input class="input" name="email" placeholder="Mail (email)" value="{escape(email or '')}" autocomplete="off" />
        <select class="input" name="tier">
          <option value="">Tier de cliente</option>
          <option value="VIP" {"selected" if tier == "VIP" else ""}>VIP</option>
          <option value="alto" {"selected" if tier == "alto" else ""}>alto</option>
          <option value="medio" {"selected" if tier == "medio" else ""}>medio</option>
          <option value="bajo" {"selected" if tier == "bajo" else ""}>bajo</option>
        </select>
        <input class="input" name="max_amount" type="number" min="0" step="1" placeholder="Monto maximo" value="{escape(max_amount or '')}" autocomplete="off" />
        <select class="input" name="purchase_status">
          <option value="">Estado de compras</option>
          <option value="pending" {"selected" if purchase_status == "pending" else ""}>pendiente</option>
          <option value="approved" {"selected" if purchase_status == "approved" else ""}>aprobada</option>
          <option value="rejected" {"selected" if purchase_status == "rejected" else ""}>rechazada</option>
          <option value="failed" {"selected" if purchase_status == "failed" else ""}>fallida</option>
        </select>
      </div>
      <div class="filter-group filter-group-dates">
        <div class="filter-group-title">Filtros de fechas</div>
        <div class="field">
          <span class="field-label">Fecha exacta</span>
          <input class="input" name="exact_date" type="date" value="{escape(exact_date or '')}" autocomplete="off" />
        </div>
        <div class="field">
          <span class="field-label">Desde</span>
          <input class="input" name="date_from" type="date" value="{escape(date_from or '')}" autocomplete="off" />
        </div>
        <div class="field">
          <span class="field-label">Hasta</span>
          <input class="input" name="date_to" type="date" value="{escape(date_to or '')}" autocomplete="off" />
        </div>
        <div class="field">
          <span class="field-label">Inactivos desde</span>
          <input class="input" name="inactive_since" type="date" value="{escape(inactive_since or '')}" autocomplete="off" />
        </div>
      </div>
      <div class="filter-actions">
        <button class="filter-submit" type="submit">Filtrar</button>
      </div>
    </form>
    """

    customer_rows: list[list[str | SafeHTML]] = []
    for row in customers:
        customer_rows.append(
            [
                f"{escape(str(row['first_name']))} {escape(str(row['last_name']))}",
                escape(str(row.get("phone") or "-")),
                escape(str(row.get("email") or "-")),
                escape(str(row.get("tier") or "-")),
                escape(format_date_only(row.get("latest_purchase_date"))),
                str(row.get("total_purchases") or 0),
                str(row.get("pending_purchases") or 0),
                str(row.get("approved_purchases") or 0),
                str(row.get("rejected_purchases") or 0),
                str(row.get("failed_purchases") or 0),
                SafeHTML(f'<a href="/admin/customers/{row["id"]}">Ver</a>'),
            ]
        )

    purchase_rows: list[list[str | SafeHTML]] = []
    for row in purchases:
        purchase_rows.append(
            [
                str(row["id"]),
                escape(f"{str(row.get('first_name') or '').strip()} {str(row.get('last_name') or '').strip()}".strip() or "-"),
                escape(str(row.get("phone") or "-")),
                escape(str(row.get("tier") or "-")),
                escape(str(row.get("description") or "-")),
                escape(_purchase_amount_display(row.get("amount"))),
                escape(format_dt(row.get("purchase_date"))),
                SafeHTML(status_badge(str(row.get("status") or "unknown"))),
                purchase_description_popup(int(row["id"]), description=row.get("description"), amount=row.get("amount"), return_to=_admin_return_path(request)),
                purchase_amount_form(int(row["id"]), description=row.get("description"), amount=row.get("amount"), return_to=_admin_return_path(request)),
                purchase_status_actions(int(row["id"]), str(row.get("status") or ""), return_to),
                SafeHTML(f'<span class="compact-mail">{escape(str(row.get("email") or "-"))}</span>'),
            ]
        )

    daily_rows = [
        [
            escape(str(item["day"])),
            str(item["attempts"]),
            str(item["purchases"]),
            str(item["approved"]),
            str(item["rejected"]),
            str(item["failed"]),
            str(item["pending"]),
        ]
        for item in daily
    ]

    body = f"""
    <style>
      .filter-group {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 0.75rem;
        padding: 0.9rem;
        border: 1px solid rgba(148,163,184,0.14);
        border-radius: 16px;
        background: rgba(2, 6, 23, 0.28);
        min-width: 0;
      }}
      .shell-light .filter-group {{
        background: #f8fafc;
        border-color: #dbe3ef;
      }}
      .filter-group-dates {{
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      }}
      .filters {{
        width: 100%;
        grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.95fr);
        align-items: start;
        gap: 0.85rem;
      }}
      .filters > .filter-group,
      .filters > .filter-actions {{
        min-width: 0;
      }}
      .filter-group-title {{
        grid-column: 1 / -1;
        font-size: 0.8rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .field {{
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
      }}
      .field-label {{
        font-size: 0.78rem;
        font-weight: 700;
        color: var(--muted);
      }}
      .filter-actions {{
        grid-column: 1 / -1;
        display: flex;
        justify-content: flex-end;
        margin-top: 0.2rem;
      }}
      .filter-submit {{
        width: auto;
        min-width: 110px;
        padding: 0.5rem 0.85rem;
        font-size: 0.85rem;
        border-radius: 10px;
        line-height: 1;
      }}
      .section-panel {{
        margin-top: 1rem;
      }}
      .section-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.75rem;
        margin-bottom: 0.75rem;
      }}
      .section-title {{
        margin: 0;
      }}
      .section-toggle {{
        width: auto;
        min-width: 40px;
        height: 40px;
        padding: 0 0.7rem;
        border-radius: 10px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.35rem;
        font-size: 0.9rem;
        line-height: 1;
        flex: 0 0 auto;
      }}
      .section-toggle-icon {{
        font-size: 1rem;
        line-height: 1;
      }}
      .section-body[hidden] {{
        display: none !important;
      }}
      .table-scroll-container {{
        max-height: calc(5 * 3.6rem + 3.25rem);
        overflow-y: auto;
        scrollbar-gutter: stable;
      }}
      .table-scroll-container table {{
        width: 100%;
      }}
      .table-scroll-container table thead th {{
        position: sticky;
        top: 0;
        z-index: 3;
        background: rgba(2, 6, 23, 0.96);
      }}
      .shell-light .table-scroll-container table thead th {{
        background: #ffffff;
      }}
      .compact-mail {{
        display: inline-block;
        max-width: 150px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        vertical-align: middle;
      }}
      .mini-dialog {{
        border: 1px solid rgba(148,163,184,0.24);
        border-radius: 16px;
        padding: 0;
        background: rgba(15, 23, 42, 0.98);
        color: var(--text);
        box-shadow: 0 24px 70px rgba(0,0,0,0.35);
        width: min(92vw, 360px);
      }}
      .shell-light .mini-dialog {{
        background: #ffffff;
      }}
      .mini-dialog::backdrop {{
        background: rgba(2, 6, 23, 0.45);
      }}
      .mini-dialog form {{
        padding: 1rem;
      }}
      .mini-dialog textarea {{
        min-height: 96px;
        resize: vertical;
      }}
      .purchases-section table th:nth-child(8),
      .purchases-section table td:nth-child(8) {{
        min-width: 170px;
        white-space: nowrap;
      }}
      .purchases-scrollbar {{
        overflow-x: auto;
        overflow-y: hidden;
        height: 16px;
        margin: 0.15rem 0;
        scrollbar-gutter: stable;
      }}
      .purchases-scrollbar-spacer {{
        height: 1px;
      }}
      .purchases-table-scroll {{
        overflow-x: auto;
        overflow-y: auto;
        max-height: calc(5 * 3.6rem + 3.25rem);
        scrollbar-gutter: stable;
      }}
      .purchases-table-scroll table thead th {{
        position: sticky;
        top: 0;
        z-index: 3;
        background: rgba(2, 6, 23, 0.96);
      }}
      .shell-light .purchases-table-scroll table thead th {{
        background: #ffffff;
      }}
    </style>
    {cards}
    <div class="panel filters-panel">
      <div class="small">Filtros activos</div>
      <div class="filter-summary">{filters_summary}</div>
    </div>
    <div class="panel filters-panel">{filter_form}</div>
    <div class="panel section-panel" data-admin-section="activity">
      <div class="section-header">
        <h2 class="section-title">Actividad diaria</h2>
        <button class="section-toggle" type="button" data-toggle-section aria-expanded="false">
          <span class="section-toggle-icon" aria-hidden="true">▸</span>
        </button>
      </div>
      <div class="section-body" hidden>
        <div class="table-scroll-container activity-section">
          {table(["Dia", "Interacciones", "Compras", "Aprobadas", "Rechazadas", "Fallidas", "Pendientes"], daily_rows)}
        </div>
      </div>
    </div>
    <div class="panel section-panel" data-admin-section="customers">
      <div class="section-header">
        <h2 class="section-title">Clientes</h2>
        <button class="section-toggle" type="button" data-toggle-section aria-expanded="false">
          <span class="section-toggle-icon" aria-hidden="true">▸</span>
        </button>
      </div>
      <div class="section-body" hidden>
        <div class="table-scroll-container customers-section">
          {table(["Cliente", "Telefono", "Mail", "Tier", "Ultima compra", "Total", "Pend.", "Aprob.", "Rech.", "Fall.", "Detalle"], customer_rows)}
        </div>
      </div>
    </div>
    <div class="panel section-panel" data-admin-section="purchases">
      <div class="section-header">
        <h2 class="section-title">Compras</h2>
        <button class="section-toggle" type="button" data-toggle-section aria-expanded="false">
          <span class="section-toggle-icon" aria-hidden="true">▸</span>
        </button>
      </div>
      <div class="section-body purchases-section" hidden>
        <div class="purchases-scrollbar purchases-scrollbar-top" data-purchases-scrollbar>
          <div class="purchases-scrollbar-spacer" data-purchases-spacer></div>
        </div>
        <div class="purchases-table-scroll" data-purchases-table-scroll>
          {table(["ID", "Cliente", "Telefono", "Tier", "Descripcion", "Monto", "Fecha", "Estado", "Descripcion", "Monto", "Acciones", "Mail (opcional)"], purchase_rows)}
        </div>
        <div class="purchases-scrollbar purchases-scrollbar-bottom" data-purchases-scrollbar>
          <div class="purchases-scrollbar-spacer" data-purchases-spacer></div>
        </div>
      </div>
    </div>
      <script>
      if ("scrollRestoration" in window.history) {{
        window.history.scrollRestoration = "manual";
      }}

      const adminStateStorageKey = "clients_qr_admin_dashboard_state:" + window.location.pathname + window.location.search;

      function readAdminState() {{
        try {{
          const raw = window.sessionStorage.getItem(adminStateStorageKey);
          if (!raw) {{
            return null;
          }}
          const parsed = JSON.parse(raw);
          return parsed && typeof parsed === "object" ? parsed : null;
        }} catch (_error) {{
          return null;
        }}
      }}

      function writeAdminState(state) {{
        try {{
          window.sessionStorage.setItem(adminStateStorageKey, JSON.stringify(state));
        }} catch (_error) {{
          void _error;
        }}
      }}

      function collectAdminState() {{
        const openSections = Array.from(document.querySelectorAll(".section-panel"))
          .filter(function (panel) {{
            if (!(panel instanceof HTMLElement)) {{
              return false;
            }}
            const body = panel.querySelector(".section-body");
            return body instanceof HTMLElement && !body.hidden;
          }})
          .map(function (panel) {{
            return panel.getAttribute("data-admin-section") || "";
          }})
          .filter(Boolean);

        const purchasesSection = document.querySelector(".purchases-section");
        const tableScroll = purchasesSection instanceof HTMLElement
          ? purchasesSection.querySelector("[data-purchases-table-scroll]")
          : null;

        return {{
          openSections: openSections,
          windowScrollX: window.scrollX,
          windowScrollY: window.scrollY,
          purchaseScrollLeft: tableScroll instanceof HTMLElement ? tableScroll.scrollLeft : 0,
          purchaseScrollTop: tableScroll instanceof HTMLElement ? tableScroll.scrollTop : 0,
        }};
      }}

      let adminStateSaveScheduled = false;

      function scheduleAdminStateSave() {{
        if (adminStateSaveScheduled) {{
          return;
        }}
        adminStateSaveScheduled = true;
        window.requestAnimationFrame(function () {{
          adminStateSaveScheduled = false;
          writeAdminState(collectAdminState());
        }});
      }}

      function syncPurchasesScrollbars() {{
        const purchasesSection = document.querySelector(".purchases-section");
        if (!(purchasesSection instanceof HTMLElement)) {{
          return;
        }}
        const tableScroll = purchasesSection.querySelector("[data-purchases-table-scroll]");
        const scrollbars = Array.from(purchasesSection.querySelectorAll("[data-purchases-scrollbar]"));
        const spacers = Array.from(purchasesSection.querySelectorAll("[data-purchases-spacer]"));
        if (!(tableScroll instanceof HTMLElement) || !scrollbars.length || !spacers.length) {{
          return;
        }}
        const scrollWidth = tableScroll.scrollWidth;
        spacers.forEach(function (spacer) {{
          if (spacer instanceof HTMLElement) {{
            spacer.style.width = scrollWidth + "px";
          }}
        }});
        scrollbars.forEach(function (scrollbar) {{
          if (scrollbar instanceof HTMLElement && scrollbar.scrollLeft !== tableScroll.scrollLeft) {{
            scrollbar.scrollLeft = tableScroll.scrollLeft;
          }}
        }});
      }}

      function bindPurchasesScrollbars() {{
        const purchasesSection = document.querySelector(".purchases-section");
        if (!(purchasesSection instanceof HTMLElement)) {{
          return;
        }}
        const tableScroll = purchasesSection.querySelector("[data-purchases-table-scroll]");
        const scrollbars = Array.from(purchasesSection.querySelectorAll("[data-purchases-scrollbar]"));
        if (!(tableScroll instanceof HTMLElement) || !scrollbars.length) {{
          return;
        }}

        let syncing = false;
        function syncFrom(source) {{
          if (syncing) {{
            return;
          }}
          syncing = true;
          const nextScrollLeft = source.scrollLeft;
          tableScroll.scrollLeft = nextScrollLeft;
          scrollbars.forEach(function (scrollbar) {{
            if (scrollbar !== source) {{
              scrollbar.scrollLeft = nextScrollLeft;
            }}
          }});
          syncing = false;
        }}

        [tableScroll].concat(scrollbars).forEach(function (scrollbar) {{
          scrollbar.addEventListener("scroll", function (event) {{
            const target = event.currentTarget;
            if (target instanceof HTMLElement) {{
              syncFrom(target);
              scheduleAdminStateSave();
            }}
          }}, {{ passive: true }});
        }});

        if (typeof ResizeObserver !== "undefined") {{
          const observer = new ResizeObserver(function () {{
            syncPurchasesScrollbars();
          }});
          observer.observe(tableScroll);
        }} else {{
          window.addEventListener("resize", syncPurchasesScrollbars, {{ passive: true }});
        }}

        syncPurchasesScrollbars();
      }}

      function restoreAdminState() {{
        const state = readAdminState();
        if (!state) {{
          return;
        }}

        const openSections = new Set(Array.isArray(state.openSections) ? state.openSections : []);
        const panels = Array.from(document.querySelectorAll(".section-panel"));
        panels.forEach(function (panel) {{
          if (!(panel instanceof HTMLElement)) {{
            return;
          }}
          const body = panel.querySelector(".section-body");
          const toggle = panel.querySelector("[data-toggle-section]");
          const sectionKey = panel.getAttribute("data-admin-section") || "";
          const shouldOpen = openSections.has(sectionKey);
          if (body instanceof HTMLElement) {{
            body.hidden = !shouldOpen;
          }}
          if (toggle instanceof HTMLElement) {{
            toggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
            const icon = toggle.querySelector(".section-toggle-icon");
            if (icon) {{
              icon.textContent = shouldOpen ? "▾" : "▸";
            }}
          }}
        }});

        window.requestAnimationFrame(function () {{
          syncPurchasesScrollbars();

          const purchasesSection = document.querySelector(".purchases-section");
          const tableScroll = purchasesSection instanceof HTMLElement
            ? purchasesSection.querySelector("[data-purchases-table-scroll]")
            : null;

          if (tableScroll instanceof HTMLElement) {{
            tableScroll.scrollLeft = Number(state.purchaseScrollLeft) || 0;
            tableScroll.scrollTop = Number(state.purchaseScrollTop) || 0;
            syncPurchasesScrollbars();
          }}

          window.scrollTo(Number(state.windowScrollX) || 0, Number(state.windowScrollY) || 0);
        }});
      }}

      document.addEventListener("DOMContentLoaded", function () {{
        bindPurchasesScrollbars();
        restoreAdminState();
      }});

      window.addEventListener("scroll", scheduleAdminStateSave, {{ passive: true }});
      window.addEventListener("pagehide", function () {{
        writeAdminState(collectAdminState());
      }});
      document.addEventListener("submit", function () {{
        writeAdminState(collectAdminState());
      }}, true);

      document.addEventListener("click", function (event) {{
        const target = event.target;
        if (!(target instanceof HTMLElement)) {{
          return;
        }}
        const sectionToggle = target.closest("[data-toggle-section]");
        if (sectionToggle instanceof HTMLElement) {{
          const panel = sectionToggle.closest(".section-panel");
          if (panel) {{
            const body = panel.querySelector(".section-body");
            const icon = sectionToggle.querySelector(".section-toggle-icon");
            const expanded = sectionToggle.getAttribute("aria-expanded") === "true";
            sectionToggle.setAttribute("aria-expanded", expanded ? "false" : "true");
            if (body instanceof HTMLElement) {{
              body.hidden = expanded;
              if (body.classList.contains("purchases-section") && !expanded) {{
                window.setTimeout(syncPurchasesScrollbars, 0);
              }}
            }}
            if (icon) {{
              icon.textContent = expanded ? "▸" : "▾";
            }}
            scheduleAdminStateSave();
          }}
          return;
        }}
        const openDialogId = target.getAttribute("data-open-dialog");
        if (openDialogId) {{
          const dialog = document.getElementById(openDialogId);
          if (dialog instanceof HTMLDialogElement && !dialog.open) {{
            dialog.showModal();
          }}
          return;
        }}
        if (target.hasAttribute("data-close-dialog")) {{
          const dialog = target.closest("dialog");
          if (dialog instanceof HTMLDialogElement && dialog.open) {{
            dialog.close();
          }}
        }}
      }});
    </script>
    """
    return page("Panel de administracion", body, header_html=header_html, shell_class="shell shell-light")


@router.get("/api/admin/customers")
async def api_admin_customers(
    request: Request,
    admin_email: str = Depends(require_admin),
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    phone: str | None = Query(None),
    email: str | None = Query(None),
    tier: str | None = Query(None),
    exact_date: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    inactive_since: str | None = Query(None),
    purchase_status: str | None = Query(None),
):
    _ = request, admin_email
    try:
        normalized_tier = normalize_customer_tier(tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    customers = list_customers(
        db,
        name=q,
        phone=phone,
        email=email,
        tier=normalized_tier,
        exact_date=parse_date(exact_date),
        date_from=parse_date(date_from),
        date_to=parse_date(date_to),
        inactive_since=parse_date(inactive_since),
        purchase_status=purchase_status,
    )
    return JSONResponse({"items": customers})


@router.get("/admin/customers/{customer_id}", response_class=HTMLResponse)
async def admin_customer_detail(
    request: Request,
    customer_id: int,
    admin_email: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _ = request, admin_email
    customer = db.execute(
        text(
            """
            SELECT c.id, c.first_name, c.last_name, c.phone, c.email, c.tier, c.google_sub, c.status, c.created_at, c.updated_at
            FROM customers c
            WHERE c.id = :customer_id
            """
        ),
        {"customer_id": customer_id},
    ).mappings().first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    return_to = _admin_return_path(request, fallback=f"/admin/customers/{customer_id}")
    filtered_purchases = list_purchases(db, customer_id=customer_id)
    rows = [
        [
            str(p["id"]),
            escape(format_dt(p.get("purchase_date"))),
            escape(str(p.get("description") or "-")),
            escape(_purchase_amount_display(p.get("amount"))),
            SafeHTML(status_badge(str(p.get("status") or ""))),
            escape(str(p.get("source_token") or "-")),
            purchase_status_actions(int(p["id"]), str(p.get("status") or ""), return_to),
        ]
        for p in filtered_purchases
    ]

    body = f"""
    <p><a class="btn" href="/admin">Volver al panel</a></p>
    <div class="notice">
      <strong>{escape(str(customer["first_name"]))} {escape(str(customer["last_name"]))}</strong><br />
      Tel: {escape(str(customer["phone"] or "-"))}<br />
      Mail: {escape(str(customer["email"] or "-"))}<br />
      Tier: {escape(str(customer["tier"] or "-"))}<br />
      Google Sub: {escape(str(customer["google_sub"] or "-"))}<br />
      Estado: {escape(str(customer["status"]))}
    </div>
    <div class="panel">
      <h2>Editar cliente</h2>
      {customer_tier_form(customer_id, tier=str(customer["tier"] or ""), return_to=return_to)}
    </div>
    <div class="panel">
      <h2>Compras del cliente</h2>
      {table(["ID", "Fecha", "Descripcion", "Monto", "Estado", "Origen", "Acciones"], rows)}
    </div>
    """
    return page("Detalle de cliente", body, subtitle="Historial completo por cliente")


@router.post("/api/admin/customers/{customer_id}/tier")
async def api_admin_customer_update_tier(
    request: Request,
    customer_id: int,
    tier: str | None = Form(None),
    return_to: str | None = Form(None),
    admin_email: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _ = request
    try:
        update_customer_tier(db, customer_id=customer_id, tier=tier, actor_email=admin_email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url=_safe_redirect_path(return_to, fallback=f"/admin/customers/{customer_id}"), status_code=303)


@router.post("/api/admin/purchases/{purchase_id}/details")
async def api_admin_purchase_update_details(
    request: Request,
    purchase_id: int,
    description: str | None = Form(None),
    amount: str | None = Form(None),
    return_to: str | None = Form(None),
    admin_email: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _ = request
    try:
        update_purchase_details(db, purchase_id=purchase_id, description=description, amount=amount, actor_email=admin_email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url=_safe_redirect_path(return_to), status_code=303)


@router.post("/api/admin/purchases/{purchase_id}/approve")
async def api_admin_purchase_approve(
    request: Request,
    purchase_id: int,
    return_to: str | None = Form(None),
    admin_email: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _ = request
    try:
        approve_purchase(db, purchase_id, admin_email)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url=_safe_redirect_path(return_to), status_code=303)


@router.post("/api/admin/purchases/{purchase_id}/reject")
async def api_admin_purchase_reject(
    request: Request,
    purchase_id: int,
    return_to: str | None = Form(None),
    admin_email: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _ = request
    try:
        reject_purchase(db, purchase_id, admin_email)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url=_safe_redirect_path(return_to), status_code=303)


@router.post("/api/admin/purchases/{purchase_id}/status")
async def api_admin_purchase_set_status(
    request: Request,
    purchase_id: int,
    status: str = Form(...),
    return_to: str | None = Form(None),
    admin_email: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _ = request
    try:
        set_purchase_status(db, purchase_id, status, admin_email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(url=_safe_redirect_path(return_to), status_code=303)
