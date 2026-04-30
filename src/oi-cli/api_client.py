from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any


logger = logging.getLogger("oi")
DEFAULT_API_BASE = "http://localhost:8788"


class GatewayRequestError(Exception):
    """The gateway rejected a request."""


class GatewayConnectionError(Exception):
    """The gateway could not be reached."""


class APIClient:
    """Lightweight HTTP client for the oi-gateway API."""

    def __init__(self, base_url: str = DEFAULT_API_BASE) -> None:
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _read_json_response(response: Any) -> dict[str, Any]:
        return json.loads(response.read().decode())

    @staticmethod
    def _read_http_error_message(exc: urllib.error.HTTPError) -> str:
        try:
            error_body = json.loads(exc.read().decode())
            return f"API error ({exc.code}): {error_body.get('error', exc.reason)}"
        except Exception:
            return f"HTTP error: {exc.reason}"

    def _request_json(self, request: str | urllib.request.Request, timeout: int) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return self._read_json_response(response)
        except urllib.error.HTTPError as exc:
            raise GatewayRequestError(self._read_http_error_message(exc)) from exc
        except urllib.error.URLError as exc:
            raise GatewayConnectionError(f"Connection error: {exc}") from exc

    def get(self, path: str) -> dict[str, Any]:
        return self._request_json(f"{self.base_url}{path}", timeout=5)

    def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._request_json(request, timeout=10)
