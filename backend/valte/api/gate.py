"""Who may call what.

HappyRobot reaches us through a public tunnel, and a tunnel exposes the
whole server, not just the callbacks. Only this machine is trusted: any
request that comes from outside (it carries X-Forwarded-*, or its Host is
not loopback) may use the HappyRobot contracts (bearer-protected further
in), the one-time approval links sent by email, and the static front.
Everything else — reading a crisis, approving an action, injecting events —
needs the dashboard key, and is refused outright if no key is configured.

Pure ASGI (not BaseHTTPMiddleware) so the event stream is never buffered.
"""

import json
from urllib.parse import parse_qs

from valte.settings import settings

PUBLIC = ("/perceptions", "/state", "/decisions", "/api/snapshot", "/api/commands", "/hr/", "/a/", "/health", "/app")
LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]", "testserver"}


def is_external(headers: dict[bytes, bytes]) -> bool:
    if b"x-forwarded-for" in headers or b"x-forwarded-host" in headers or b"x-real-ip" in headers:
        return True
    host = headers.get(b"host", b"").decode("latin-1").rsplit(":", 1)[0] if b"host" in headers else ""
    return host.lower() not in LOOPBACK


class ExternalGate:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "/")
        headers = dict(scope.get("headers") or [])
        if path == "/" or path.startswith(PUBLIC) or not is_external(headers) or scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)

        key = settings.valte_dashboard_token
        supplied = headers.get(b"x-valte-key", b"").decode() or \
            (parse_qs(scope.get("query_string", b"").decode()).get("key") or [""])[0]
        if key and supplied == key:
            return await self.app(scope, receive, send)

        body = json.dumps({"detail": "Solo accesible desde esta máquina. Desde fuera hace falta la clave del dashboard "
                                     "(VALTE_DASHBOARD_TOKEN) en ?key= o en la cabecera X-Valte-Key."}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
