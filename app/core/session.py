from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any


class SignedCookieSessionMiddleware:
    def __init__(
        self,
        app,
        *,
        secret_key: str,
        cookie_name: str = "clients_qr_session",
        https_only: bool = False,
        same_site: str = "lax",
        max_age: int = 60 * 60 * 24 * 7,
    ) -> None:
        self.app = app
        self.secret_key = secret_key.encode("utf-8")
        self.cookie_name = cookie_name
        self.https_only = https_only
        self.same_site = same_site
        self.max_age = max_age

    def _sign(self, payload: str) -> str:
        return hmac.new(self.secret_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def _encode(self, session: dict[str, Any]) -> str:
        payload = json.dumps(session, separators=(",", ":"), ensure_ascii=False, default=str)
        encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
        return f"{encoded}.{self._sign(encoded)}"

    def _decode(self, value: str | None) -> dict[str, Any]:
        if not value or "." not in value:
            return {}
        encoded, signature = value.rsplit(".", 1)
        expected = self._sign(encoded)
        if not hmac.compare_digest(expected, signature):
            return {}
        try:
            payload = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
            data = json.loads(payload)
            if isinstance(data, dict):
                return data
        except Exception:  # noqa: BLE001
            return {}
        return {}

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        cookie_header = headers.get(b"cookie", b"").decode("latin1")
        cookies: dict[str, str] = {}
        for part in cookie_header.split(";"):
            if "=" in part:
                name, value = part.split("=", 1)
                cookies[name.strip()] = value.strip()

        scope["session"] = self._decode(cookies.get(self.cookie_name))

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                session = scope.get("session") or {}
                headers_list = message.setdefault("headers", [])
                if session:
                    encoded = self._encode(session)
                    cookie = (
                        f"{self.cookie_name}={encoded}; Path=/; Max-Age={self.max_age}; "
                        f"HttpOnly; SameSite={self.same_site}"
                    )
                    if self.https_only:
                        cookie += "; Secure"
                    headers_list.append((b"set-cookie", cookie.encode("latin1")))
                else:
                    cookie = f"{self.cookie_name}=; Path=/; Max-Age=0; HttpOnly; SameSite={self.same_site}"
                    if self.https_only:
                        cookie += "; Secure"
                    headers_list.append((b"set-cookie", cookie.encode("latin1")))
            await send(message)

        await self.app(scope, receive, send_wrapper)

