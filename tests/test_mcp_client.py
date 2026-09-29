"""Tests for mcp_server/client.py - the thin wrapper the MCP server uses to talk to the app.

These cover the same role boundaries as test_app_api.py, but through the client the MCP tools
actually call, so a regression in how the client builds requests or interprets responses (as
opposed to a regression in the Flask app itself) shows up here specifically.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))
from client import CatalogApiError, CatalogClient, CatalogCredentials  # noqa: E402


def _client(live_app, username: str, password: str) -> CatalogClient:
    return CatalogClient(CatalogCredentials(base_url=live_app.base_url, username=username, password=password))


class TestLogin:
    def test_wrong_password_raises(self, live_app):
        with pytest.raises(CatalogApiError) as excinfo:
            _client(live_app, "admin", "wrong-password")
        assert excinfo.value.status_code == 401

    def test_correct_credentials_succeed_for_each_role(self, live_app):
        for username, password in (("admin", "admin"), ("editor", "editorPass123"), ("viewer", "viewerPass123")):
            _client(live_app, username, password)  # no exception


class TestReadOnlyClient:
    def test_can_list_tools(self, live_app):
        client = _client(live_app, "viewer", "viewerPass123")
        tools = client.get("/api/tools")
        assert isinstance(tools, list)
        assert tools

    def test_add_tool_raises_forbidden(self, live_app):
        client = _client(live_app, "viewer", "viewerPass123")
        with pytest.raises(CatalogApiError) as excinfo:
            client.post_form("/api/tools", {"name": "x", "category": "die", "status": "active"})
        assert excinfo.value.status_code == 403


class TestReadWriteClient:
    def test_add_then_delete_tool(self, live_app):
        client = _client(live_app, "editor", "editorPass123")
        created = client.post_form(
            "/api/tools",
            {"name": "MCP client test tool", "category": "die", "status": "active", "client": "Client Test"},
        )
        assert created["success"] is True
        tool_id = created["tool"]["id"]

        deleted = client.delete(f"/api/tools/{tool_id}")
        assert deleted["success"] is True

        remaining = [t for t in client.get("/api/tools") if t["id"] == tool_id]
        assert remaining == []


class TestConnectionError:
    def test_unreachable_host_raises_with_zero_status(self):
        with pytest.raises(CatalogApiError) as excinfo:
            CatalogClient(CatalogCredentials(base_url="http://127.0.0.1:1", username="admin", password="admin"))
        assert excinfo.value.status_code == 0
