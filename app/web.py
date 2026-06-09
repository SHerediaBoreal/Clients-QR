from __future__ import annotations

import base64
from datetime import date, datetime, time
from html import escape
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.core.timezones import BUENOS_AIRES_TZ, to_buenos_aires


class SafeHTML(str):
    """Marker type for trusted HTML fragments rendered by the table helper."""


@lru_cache(maxsize=1)
def _favicon_data_uri() -> str:
    favicon_path = Path(__file__).resolve().parent / "utlis" / "pagina_3.png"
    return "data:image/png;base64," + base64.b64encode(favicon_path.read_bytes()).decode("ascii")


@lru_cache(maxsize=1)
def _public_background_data_uri() -> str:
    background_path = Path(__file__).resolve().parent / "utlis" / "pagina_2.png"
    return "data:image/png;base64," + base64.b64encode(background_path.read_bytes()).decode("ascii")


def _coerce_datetime(value: datetime | date | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=BUENOS_AIRES_TZ)
    if isinstance(value, str):
        candidate = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        return parsed
    return None


def format_dt(value: datetime | date | str | None) -> str:
    parsed = _coerce_datetime(value)
    if parsed is None:
        return "-"
    return to_buenos_aires(parsed).strftime("%Y-%m-%d %H:%M:%S")


def format_date_only(value: datetime | date | str | None) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    parsed = _coerce_datetime(value)
    if parsed is None:
        return "-"
    return to_buenos_aires(parsed).strftime("%Y-%m-%d")


def status_badge(status: str) -> str:
    palette = {
        "pending": "background:#f59e0b;color:#111827;",
        "approved": "background:#16a34a;color:#ffffff;",
        "rejected": "background:#dc2626;color:#ffffff;",
        "failed": "background:#6b7280;color:#ffffff;",
        "success": "background:#16a34a;color:#ffffff;",
        "failure": "background:#dc2626;color:#ffffff;",
    }
    style = palette.get(status, "background:#334155;color:#ffffff;")
    return f'<span style="padding:0.2rem 0.55rem;border-radius:999px;font-size:0.75rem;font-weight:700;{style}">{escape(status)}</span>'


def page(
    title: str,
    body: str,
    *,
    subtitle: str | None = None,
    header_html: str | None = None,
    body_class: str = "",
    shell_class: str = "shell",
) -> HTMLResponse:
    subtitle_html = f"<p class='subtitle'>{escape(subtitle)}</p>" if subtitle else ""
    default_header = f"""
      <div class="header">
        <div>
          <h1>{escape(title)}</h1>
          {subtitle_html}
        </div>
        <div class="stack">
          <span class="chip">{escape(settings.app_name)}</span>
          <span class="chip">{escape(settings.public_token)}</span>
        </div>
      </div>
    """
    header_block = header_html if header_html is not None else default_header
    html = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="icon" type="image/png" href="{_favicon_data_uri()}" />
  <title>{escape(title)} - {escape(settings.app_name)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #0f172a;
      --card: #111827;
      --panel: #0b1220;
      --line: #243044;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --success: #16a34a;
      --danger: #dc2626;
      --warning: #f59e0b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(56,189,248,0.18), transparent 30%),
        radial-gradient(circle at top right, rgba(22,163,74,0.13), transparent 24%),
        linear-gradient(180deg, #020617 0%, #0f172a 100%);
      color: var(--text);
      position: relative;
    }}
    body.body-public-bg {{
      background:
        linear-gradient(rgba(2, 6, 23, 0.42), rgba(2, 6, 23, 0.42)),
        url("{_public_background_data_uri()}") center center / cover no-repeat fixed;
    }}
    body.body-public-bg,
    body.body-public-bg::before {{
      min-height: 100vh;
    }}
    body.body-public-bg::before {{
      content: "";
      position: fixed;
      inset: 0;
      background:
        radial-gradient(circle at top left, rgba(56,189,248,0.16), transparent 32%),
        radial-gradient(circle at bottom right, rgba(34,197,94,0.12), transparent 28%);
      pointer-events: none;
      z-index: 0;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    .container {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 1.25rem;
      position: relative;
      z-index: 1;
    }}
    .shell {{
      background: rgba(15, 23, 42, 0.82);
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 20px;
      padding: 1.25rem;
      box-shadow: 0 24px 80px rgba(0,0,0,.35);
      backdrop-filter: blur(10px);
    }}
    .shell-light {{
      background: #ffffff;
      border: 1px solid #dbe3ef;
      box-shadow: 0 18px 60px rgba(15, 23, 42, 0.12);
      color: #0f172a;
      --text: #0f172a;
      --muted: #64748b;
      --card: #f8fafc;
      --panel: #ffffff;
      --line: #e2e8f0;
    }}
    .shell-auth {{
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.18), transparent 22%),
        linear-gradient(135deg, #243b8b 0%, #132b72 38%, #0c1d4f 68%, #08112f 100%);
      border: 1px solid rgba(255,255,255,0.12);
      box-shadow: 0 28px 90px rgba(9, 15, 36, 0.45);
      color: #0f172a;
      overflow: hidden;
      padding: 0;
    }}
    .shell-auth .auth-layout {{
      display: grid;
      grid-template-columns: minmax(320px, 390px) minmax(0, 1fr);
      min-height: 720px;
    }}
    .shell-auth .auth-card {{
      background: #ffffff;
      color: #0f172a;
      padding: 2rem 1.9rem;
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 1rem;
    }}
    .shell-auth .auth-brand {{
      display: inline-flex;
      align-self: flex-start;
      padding: 0.45rem 0.7rem;
      border-radius: 999px;
      background: #eef2ff;
      color: #1d4ed8;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }}
    .shell-auth .auth-title {{
      margin: 0;
      font-size: 2rem;
      line-height: 1.02;
      letter-spacing: -0.04em;
      color: #0f172a;
    }}
    .shell-auth .auth-copy {{
      margin: 0;
      color: #475569;
      line-height: 1.55;
      max-width: 30ch;
    }}
    .shell-auth .auth-stack {{
      display: flex;
      flex-direction: column;
      gap: 0.9rem;
      margin-top: 0.35rem;
    }}
    .shell-auth .auth-section {{
      border-radius: 18px;
      border: 1px solid #e2e8f0;
      background: #ffffff;
      padding: 1rem;
    }}
    .shell-auth .auth-section--soft {{
      background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
    }}
    .shell-auth .auth-section h2 {{
      margin-bottom: 0.45rem;
      color: #0f172a;
    }}
    .shell-auth .auth-section .small {{
      color: #64748b;
    }}
    .shell-auth .auth-visual {{
      position: relative;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem;
      color: #ffffff;
      background:
        radial-gradient(circle at 30% 18%, rgba(255, 233, 184, 0.9), transparent 18%),
        radial-gradient(circle at 74% 18%, rgba(174, 214, 255, 0.5), transparent 24%),
        radial-gradient(circle at 55% 85%, rgba(59, 130, 246, 0.5), transparent 34%),
        linear-gradient(135deg, #193483 0%, #0d1d4c 58%, #1f4fc3 100%);
    }}
    .shell-auth .auth-visual::before {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(115deg, rgba(255,255,255,0.15), transparent 28%),
        radial-gradient(circle at 58% 40%, rgba(255,255,255,0.10), transparent 26%);
      mix-blend-mode: screen;
      pointer-events: none;
    }}
    .shell-auth .auth-visual-content {{
      position: relative;
      z-index: 1;
      max-width: 460px;
      margin: 0 auto;
      text-align: left;
    }}
    .shell-auth .auth-visual-kicker {{
      margin: 0 0 0.35rem 0;
      text-transform: uppercase;
      letter-spacing: 0.22em;
      font-size: 0.7rem;
      color: rgba(255,255,255,0.8);
    }}
    .shell-auth .auth-visual h2 {{
      margin: 0;
      font-size: clamp(3rem, 6vw, 4.6rem);
      line-height: 0.95;
      letter-spacing: -0.08em;
      color: #ffffff;
    }}
    .shell-auth .auth-visual p {{
      margin: 1rem 0 0;
      max-width: 22ch;
      color: rgba(255,255,255,0.82);
      line-height: 1.5;
    }}
    .shell-auth .auth-glow {{
      position: absolute;
      border-radius: 999px;
      filter: blur(2px);
      pointer-events: none;
      opacity: 0.95;
    }}
    .shell-auth .auth-glow--a {{
      width: 220px;
      height: 220px;
      left: -40px;
      top: 8%;
      background: radial-gradient(circle, rgba(255, 222, 173, 0.65) 0%, rgba(255, 222, 173, 0.2) 48%, rgba(255, 222, 173, 0) 75%);
    }}
    .shell-auth .auth-glow--b {{
      width: 280px;
      height: 280px;
      right: -55px;
      top: 18%;
      background: radial-gradient(circle, rgba(174, 214, 255, 0.55) 0%, rgba(174, 214, 255, 0.16) 48%, rgba(174, 214, 255, 0) 76%);
    }}
    .shell-auth .auth-glow--c {{
      width: 220px;
      height: 220px;
      right: 18%;
      bottom: -60px;
      background: radial-gradient(circle, rgba(59, 130, 246, 0.5) 0%, rgba(59, 130, 246, 0.12) 48%, rgba(59, 130, 246, 0) 76%);
    }}
    .shell-auth .auth-mini {{
      margin-top: 1.35rem;
      display: inline-flex;
      gap: 0.5rem;
      align-items: center;
      padding: 0.6rem 0.8rem;
      border-radius: 999px;
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.14);
      backdrop-filter: blur(10px);
      color: rgba(255,255,255,0.86);
      font-size: 0.85rem;
    }}
    .shell-auth .auth-mini span {{
      width: 0.5rem;
      height: 0.5rem;
      border-radius: 999px;
      background: #6ee7ff;
      box-shadow: 0 0 18px rgba(110,231,255,0.85);
    }}
    @media (max-width: 900px) {{
      .shell-auth .auth-layout {{
        grid-template-columns: 1fr;
      }}
      .shell-auth .auth-visual {{
        min-height: 340px;
      }}
    }}
    .shell-public {{
      min-height: calc(100dvh - 2.5rem);
      display: flex;
      flex-direction: column;
      justify-content: center;
      background: rgba(8, 15, 36, 0.42);
      border-color: rgba(96, 165, 250, 0.26);
      box-shadow: 0 24px 80px rgba(0,0,0,.28);
      backdrop-filter: blur(14px);
    }}
    .public-center {{
      width: 100%;
      max-width: 760px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }}
    .shell-public-result .public-center {{
      max-width: 640px;
    }}
    .public-center .notice,
    .public-center .card {{
      width: 100%;
    }}
    .shell-public .public-center {{
      min-height: calc(100dvh - 7rem);
    }}
    .shell-public .public-center .card {{
      max-width: 760px;
      margin: 0 auto;
    }}
    .shell-public .public-register-grid {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .shell-public .public-register-actions {{
      margin-top: 1rem;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.75rem;
    }}
    .shell-public .public-register-actions .btn {{
      width: 100%;
    }}
    .header {{
      display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap;
      align-items:flex-end; margin-bottom: 1rem;
    }}
    .admin-header {{
      display:grid;
      grid-template-columns: minmax(0, 1fr) auto minmax(0, 0.9fr);
      align-items:center;
      gap:1rem;
      margin-bottom: 1rem;
    }}
    .admin-header-left {{
      min-width: 0;
    }}
    .admin-header-center {{
      display:flex;
      justify-content:center;
      align-items:center;
    }}
    .admin-header-right {{
      display:flex;
      justify-content:flex-end;
      align-items:center;
    }}
    .admin-header-title {{
      margin: 0;
      font-size: 1.6rem;
      line-height: 1.1;
    }}
    .admin-header-subtitle {{
      margin: 0.35rem 0 0 0;
      color: var(--muted);
    }}
    .admin-logo {{
      width: 300px;
      height: 200px;
      object-fit: contain;
      display: block;
      border-radius: 20px;
      filter: drop-shadow(0 12px 30px rgba(0,0,0,0.28));
      opacity: 0.95;

      -webkit-mask-image: radial-gradient(
        ellipse at center,
        rgba(0,0,0,1) 42%,
        rgba(0,0,0,0.92) 58%,
        rgba(0,0,0,0.55) 74%,
        rgba(0,0,0,0) 100%
      );

      mask-image: radial-gradient(
        ellipse at center,
        rgba(0,0,0,1) 42%,
        rgba(0,0,0,0.92) 58%,
        rgba(0,0,0,0.55) 74%,
        rgba(0,0,0,0) 100%
      );
    }}
    h1 {{ margin: 0; font-size: 1.6rem; }}
    h2 {{ margin: 0 0 0.75rem 0; font-size: 1.15rem; }}
    .subtitle {{ margin: 0.35rem 0 0 0; color: var(--muted); }}
    .grid {{ display:grid; gap:1rem; }}
    .cards {{ grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
    .card {{
      background: rgba(2, 6, 23, 0.7);
      border: 1px solid rgba(148,163,184,0.16);
      border-radius: 16px;
      padding: 1rem;
    }}
    .shell-light .card {{
      background: #f8fafc;
      border-color: #dbe3ef;
    }}
    .label {{ color: var(--muted); font-size: 0.85rem; }}
    .value {{ font-size: 1.35rem; font-weight: 700; margin-top: 0.25rem; }}
    .table-wrap {{ overflow-x:auto; border-radius: 16px; border: 1px solid rgba(148,163,184,0.16); }}
    table {{ width:100%; border-collapse: collapse; background: rgba(2, 6, 23, 0.8); }}
    .shell-light .table-wrap {{ border-color: #dbe3ef; }}
    .shell-light table {{ background: #ffffff; }}
    th, td {{ padding: 0.72rem 0.75rem; text-align:left; border-bottom: 1px solid rgba(148,163,184,0.12); vertical-align: top; }}
    .shell-light th, .shell-light td {{ border-bottom-color: #e5e7eb; color: #0f172a; }}
    th {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }}
    .shell-light th {{ color: #64748b; }}
    tr:hover td {{ background: rgba(56,189,248,0.05); }}
    .filters {{
      display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:0.75rem;
      margin: 1rem 0;
    }}
    .filters input, .filters select, .filters button, .btn, .input {{
      width: 100%;
      border-radius: 12px;
      border: 1px solid rgba(148,163,184,0.25);
      background: rgba(15, 23, 42, 0.95);
      color: var(--text);
      padding: 0.72rem 0.8rem;
      font: inherit;
    }}
    .shell-light .filters input,
    .shell-light .filters select,
    .shell-light .input {{
      background: #ffffff;
      color: #0f172a;
      border-color: #cbd5e1;
    }}
    .filters input[type="date"] {{
      color-scheme: dark;
    }}
    .filters input[type="date"]::-webkit-calendar-picker-indicator {{
      filter: invert(1);
      opacity: 1;
      cursor: pointer;
    }}
    .filters button, .btn {{
      background: linear-gradient(135deg, #38bdf8, #22c55e);
      color: #020617;
      font-weight: 700;
      border: none;
      cursor: pointer;
      text-align:center;
    }}
    .actions {{ display:flex; gap:0.5rem; flex-wrap:wrap; }}
    .actions form {{ display:inline; }}
    .row-actions {{
      display:flex;
      gap:0.35rem;
      flex-wrap:wrap;
    }}
    .row-actions form {{ display:inline; }}
    .action-btn {{
      width: auto;
      padding: 0.45rem 0.7rem;
      border-radius: 10px;
      border: 1px solid rgba(148,163,184,0.22);
      background: rgba(15, 23, 42, 0.9);
      color: var(--text);
      font-size: 0.8rem;
      font-weight: 700;
      cursor: pointer;
    }}
    .action-btn.approved {{ border-color: rgba(22,163,74,0.45); }}
    .action-btn.rejected {{ border-color: rgba(220,38,38,0.45); }}
    .action-btn.pending {{ border-color: rgba(245,158,11,0.45); }}
    .small {{ color: var(--muted); font-size: 0.875rem; }}
    .panel {{ margin-top: 1rem; }}
    .filters-panel {{
      padding: 1rem;
      background: rgba(2, 6, 23, 0.55);
      border: 1px solid rgba(148,163,184,0.16);
      border-radius: 16px;
    }}
    .stack {{ display:flex; gap:0.75rem; flex-wrap:wrap; align-items:center; }}
    .chip {{ padding:0.2rem 0.55rem; border-radius:999px; background:#1e293b; color:var(--text); font-size:0.8rem; }}
    .dashboard-actions {{
      display:flex;
      justify-content:flex-end;
      margin-bottom:1rem;
    }}
    .filter-summary {{
      display:flex;
      flex-wrap:wrap;
      gap:0.5rem;
      margin-top:0.75rem;
    }}
    .filter-chip {{
      display:flex;
      gap:0.35rem;
      align-items:center;
      padding:0.45rem 0.7rem;
      border-radius:999px;
      border:1px solid rgba(148,163,184,0.18);
      background: rgba(2, 6, 23, 0.72);
      color: var(--text);
      font-size: 0.86rem;
      line-height: 1;
    }}
    .filter-chip-label {{ color: var(--muted); font-weight:700; }}
    .filter-chip-value {{ color: var(--text); font-weight:600; }}
    .shell-light .filter-chip {{
      background: #f8fafc;
      border-color: #dbe3ef;
    }}
    .filters-panel .filters {{ margin: 0.85rem 0 0; }}
    .muted {{ color: var(--muted); }}
    .notice {{
      background: rgba(56,189,248,0.10);
      border: 1px solid rgba(56,189,248,0.30);
      padding: 0.9rem 1rem;
      border-radius: 14px;
      margin-bottom: 1rem;
    }}
    .frontend-error-banner {{
      position: fixed;
      top: 1rem;
      left: 1rem;
      right: 1rem;
      z-index: 9999;
      display: none;
      align-items: flex-start;
      gap: 0.75rem;
      padding: 0.9rem 1rem;
      border-radius: 14px;
      border: 1px solid rgba(220,38,38,0.35);
      background: rgba(17,24,39,0.96);
      color: var(--text);
      box-shadow: 0 20px 50px rgba(0,0,0,0.35);
      pointer-events: none;
    }}
    .frontend-error-banner.is-visible {{
      display: flex;
    }}
    .frontend-error-banner strong {{
      display: block;
      margin-bottom: 0.15rem;
    }}
    .frontend-error-banner span {{
      color: var(--muted);
      line-height: 1.45;
    }}
    .success {{
      background: rgba(22,163,74,0.12);
      border: 1px solid rgba(22,163,74,0.35);
    }}
    .failure {{
      background: rgba(220,38,38,0.12);
      border: 1px solid rgba(220,38,38,0.35);
    }}
    .split {{ display:grid; grid-template-columns: 1.15fr 0.85fr; gap:1rem; }}
    @media (max-width: 960px) {{
      .split {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 640px) {{
      .container {{
        padding: 0.6rem;
      }}
      .shell {{
        padding: 0.9rem;
        border-radius: 16px;
      }}
      .shell-public {{
        min-height: calc(100dvh - 1.2rem);
      }}
      .shell-public .public-center {{
        min-height: auto;
        gap: 0.7rem;
      }}
      .shell-public .public-center .card {{
        max-width: none;
      }}
      .shell-public .public-center .notice {{
        max-width: none;
      }}
      .shell-public .public-register-grid {{
        grid-template-columns: 1fr;
        gap: 0.65rem;
      }}
      .shell-public .public-register-actions {{
        grid-template-columns: 1fr;
        gap: 0.6rem;
      }}
      .shell-public .public-register-actions .btn {{
        padding: 0.78rem 0.85rem;
      }}
      .public-center .notice {{
        padding: 0.8rem 0.9rem;
      }}
      body.body-public-bg {{
        background-attachment: scroll;
        background-position: center top;
      }}
      body.body-public-bg::before {{
        position: absolute;
      }}
    }}
  </style>
</head>
<body class="{escape(body_class)}">
  <div class="frontend-error-banner" id="frontend-error-banner" role="alert" aria-live="assertive" aria-atomic="true" hidden>
    <div>
      <strong>Se produjo un error inesperado.</strong>
      <span id="frontend-error-banner-message">Recargá la página para continuar.</span>
    </div>
  </div>
  <div class="container">
    <div class="shell">
      {header_block}
      {body}
    </div>
  </div>
  <script>
    (function () {{
      const banner = document.getElementById("frontend-error-banner");
      const bannerMessage = document.getElementById("frontend-error-banner-message");

      function showGlobalErrorBanner(message) {{
        if (!(banner instanceof HTMLElement) || !(bannerMessage instanceof HTMLElement)) {{
          return;
        }}
        bannerMessage.textContent = message || "Recargá la página para continuar.";
        banner.hidden = false;
        banner.classList.add("is-visible");
      }}

      function reportUnexpectedError(source, error) {{
        try {{
          console.error("[frontend error]", source, error);
        }} catch (_consoleError) {{
          void _consoleError;
        }}

        showGlobalErrorBanner("Se detectó un error inesperado. Recargá la página e intentá nuevamente.");
      }}

      window.onerror = function (message, source, lineno, colno, error) {{
        reportUnexpectedError("window.onerror", {{
          message: message,
          source: source,
          line: lineno,
          column: colno,
          error: error,
        }});
        return false;
      }};

      window.onunhandledrejection = function (event) {{
        reportUnexpectedError("window.onunhandledrejection", event && "reason" in event ? event.reason : event);
        return false;
      }};
    }})();

    document.addEventListener("focusin", function (event) {{
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) {{
        return;
      }}
      const selectableTypes = new Set(["text", "email", "tel", "search", "url", "password", "date", "datetime-local", "month", "week"]);
      if (!selectableTypes.has(target.type)) {{
        return;
      }}
      window.setTimeout(() => {{
        try {{
          target.select();
          if (typeof target.setSelectionRange === "function" && typeof target.value === "string") {{
            target.setSelectionRange(0, target.value.length);
          }}
        }} catch (_error) {{
          void _error;
        }}
      }}, 0);
    }});
  </script>
</body>
</html>
"""
    return HTMLResponse(html)


def card_grid(items: Iterable[tuple[str, str]]) -> str:
    cards = []
    for label, value in items:
        cards.append(
            f"""
            <div class="card">
              <div class="label">{escape(label)}</div>
              <div class="value">{value}</div>
            </div>
            """
        )
    return '<div class="grid cards">' + "".join(cards) + "</div>"


def table(headers: list[str], rows: list[list[str]]) -> str:
    head_html = "".join(f"<th>{escape(head)}</th>" for head in headers)
    row_html = []
    for row in rows:
        safe_cells = []
        for cell in row:
            if isinstance(cell, SafeHTML):
                safe_cells.append(f"<td>{cell}</td>")
            else:
                safe_cells.append(f"<td>{escape(str(cell))}</td>")
        row_html.append("<tr>" + "".join(safe_cells) + "</tr>")
    return f"""
<div class="table-wrap">
  <table>
    <thead><tr>{head_html}</tr></thead>
    <tbody>{''.join(row_html) if row_html else '<tr><td colspan="'+str(len(headers))+'">Sin registros</td></tr>'}</tbody>
  </table>
</div>
"""
