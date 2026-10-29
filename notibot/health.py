"""Servidor HTTP mínimo para Render: keep-alive, /healthz y /status."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


class HealthServer:
    def __init__(
        self,
        port: int,
        state_provider: Callable[[], dict[str, Any]],
        host: str = "0.0.0.0",
    ) -> None:
        self.port = port
        self._state_provider = state_provider
        self.httpd = ThreadingHTTPServer((host, port), self._build_handler())
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None
        self._started = False

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        state_provider = self._state_provider

        class Handler(BaseHTTPRequestHandler):
            server_version = "NotiBotHealth/2.0"
            sys_version = ""

            def do_GET(self) -> None:  # noqa: N802 - API de BaseHTTPRequestHandler
                path = urlsplit(self.path).path
                state = self._safe_state()

                if path in {"/", "/health", "/keepalive"}:
                    self._send_text(
                        200,
                        "NotiBot activo 24/7",
                    )
                    return

                if path == "/healthz":
                    healthy = bool(state.get("scheduler_running"))
                    payload = {
                        "status": "ok" if healthy else "degraded",
                        "version": state.get("version"),
                        "scheduler_running": healthy,
                        "bot_username": state.get("bot_username"),
                        "last_success": state.get("last_success"),
                    }
                    self._send_json(200 if healthy else 503, payload)
                    return

                if path == "/status":
                    self._send_json(200, state)
                    return

                self._send_json(404, {"error": "not_found"})

            def do_HEAD(self) -> None:  # noqa: N802 - API de BaseHTTPRequestHandler
                path = urlsplit(self.path).path
                if path in {"/", "/health", "/keepalive", "/healthz", "/status"}:
                    self._send_headers(200, "text/plain; charset=utf-8", 0)
                else:
                    self._send_headers(404, "text/plain; charset=utf-8", 0)

            def _safe_state(self) -> dict[str, Any]:
                try:
                    state = state_provider()
                except Exception as exc:  # noqa: BLE001 - el health no debe caerse
                    log.exception("Error obteniendo el estado del bot")
                    return {"status": "error", "error": str(exc)}
                return state if isinstance(state, dict) else {"status": "unknown"}

            def _send_json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(
                    payload, ensure_ascii=False, default=str
                ).encode("utf-8")
                self._send_headers(
                    status, "application/json; charset=utf-8", len(body)
                )
                self.wfile.write(body)

            def _send_text(self, status: int, text: str) -> None:
                body = text.encode("utf-8")
                self._send_headers(
                    status, "text/plain; charset=utf-8", len(body)
                )
                self.wfile.write(body)

            def _send_headers(
                self, status: int, content_type: str, content_length: int
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(content_length))
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                log.debug("%s - %s", self.address_string(), format % args)

        return Handler

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.httpd.serve_forever,
            name="notibot-health",
            daemon=True,
        )
        self._thread.start()
        self._started = True
        log.info("Health server escuchando en el puerto %s", self.port)

    def stop(self) -> None:
        if self._started:
            self.httpd.shutdown()
            self._started = False
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        log.info("Health server detenido")
