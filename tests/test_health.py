from __future__ import annotations

import http.client
import json

from notibot.health import HealthServer


def _request(port: int, path: str) -> tuple[int, str]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        connection.close()


def test_health_endpoints() -> None:
    state = {
        "scheduler_running": True,
        "version": "2.0.0",
        "bot_username": "notibot_test",
        "last_success": None,
    }
    server = HealthServer(0, lambda: state)
    server.start()
    port = server.httpd.server_address[1]
    try:
        status, body = _request(port, "/healthz")
        assert status == 200
        assert json.loads(body)["status"] == "ok"

        status, body = _request(port, "/status")
        assert status == 200
        assert json.loads(body)["version"] == "2.0.0"

        status, body = _request(port, "/")
        assert status == 200
        assert "NotiBot" in body

        state["scheduler_running"] = False
        status, body = _request(port, "/healthz")
        assert status == 503
        assert json.loads(body)["status"] == "degraded"
    finally:
        server.stop()
