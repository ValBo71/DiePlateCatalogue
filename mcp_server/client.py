"""Thin HTTP client for the Die & Plate Catalogue Flask app.

Logs in once with the credentials given at construction time and reuses the resulting session
cookie for every request after that - exactly what a browser does. The app itself is the only
place that decides what a role may do (see ``require_role`` in ``app.py``); this client never
inspects or enforces roles, it only forwards whatever the app answers, including a 403.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


class CatalogApiError(RuntimeError):
    """Raised when the app answers with an error (4xx/5xx) or an unexpected response body."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


@dataclass
class CatalogCredentials:
    base_url: str
    username: str
    password: str

    @classmethod
    def from_env(cls) -> "CatalogCredentials":
        base_url = os.environ.get("CATALOG_BASE_URL", "http://127.0.0.1:5050").rstrip("/")
        username = os.environ.get("CATALOG_USERNAME")
        password = os.environ.get("CATALOG_PASSWORD")
        if not username or not password:
            raise RuntimeError(
                "CATALOG_USERNAME and CATALOG_PASSWORD must be set - one MCP server instance "
                "logs in as one user, so its role is fixed for the whole session."
            )
        return cls(base_url=base_url, username=username, password=password)


class CatalogClient:
    """Logs in once, then issues requests carrying the session cookie."""

    def __init__(self, credentials: CatalogCredentials):
        self._base_url = credentials.base_url
        self._session = requests.Session()
        # The app's dev server (Werkzeug, threaded=True) can wedge a request on a reused
        # keep-alive connection: hit hard enough while testing that a connection accepted at the
        # TCP level never reached the WSGI app or got logged, and the client just read-timed-out.
        # This server is meant for short-lived scripted/automation use anyway, so there is nothing
        # to gain from keep-alive; closing every connection sidesteps the dev server's fragility.
        self._session.headers["Connection"] = "close"
        self._login(credentials.username, credentials.password)

    def _login(self, username: str, password: str) -> None:
        # The app's CSRF guard (reject_cross_origin_writes) checks the Origin header against
        # the request host on every write; sending it here keeps every later POST/PUT/DELETE
        # consistent with what a real browser tab on this same origin would send.
        try:
            response = self._session.post(
                f"{self._base_url}/login",
                data={"username": username, "password": password},
                headers={"Origin": self._base_url},
                allow_redirects=False,
                timeout=10,
            )
        except requests.RequestException as exc:
            raise CatalogApiError(0, f"could not reach the app at {self._base_url}: {exc}") from exc
        if response.status_code not in (302, 200):
            raise CatalogApiError(response.status_code, "login failed - check CATALOG_USERNAME/CATALOG_PASSWORD")
        # A failed login re-renders the login page (200) instead of redirecting (302).
        if response.status_code == 200:
            raise CatalogApiError(401, "login rejected - invalid username or password")

    def _request(self, method: str, path: str, **kwargs) -> Any:
        headers = kwargs.pop("headers", {})
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            headers["Origin"] = self._base_url
        try:
            response = self._session.request(
                method, f"{self._base_url}{path}", headers=headers, timeout=15, **kwargs
            )
        except requests.RequestException as exc:
            raise CatalogApiError(0, f"could not reach the app at {self._base_url}: {exc}") from exc

        if response.status_code >= 400:
            try:
                detail = response.json().get("error", response.text)
            except ValueError:
                detail = response.text
            raise CatalogApiError(response.status_code, detail)

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post_form(self, path: str, data: dict) -> Any:
        return self._request("POST", path, data=data)

    def put_form(self, path: str, data: dict) -> Any:
        return self._request("PUT", path, data=data)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)
