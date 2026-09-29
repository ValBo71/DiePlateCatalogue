"""Drives mcp_server/server.py as a real MCP client would - over stdio, with the actual JSON-RPC
initialize handshake and tools/call requests - rather than importing its Python functions
directly. This is what proves the server behaves correctly as an MCP server, not just as a
collection of Python functions that happen to work.
"""
from __future__ import annotations

import pytest

from mcp_stdio import McpStdioSession


@pytest.fixture()
def viewer_mcp(live_app):
    session = McpStdioSession(live_app.base_url, "viewer", "viewerPass123")
    yield session
    session.close()


@pytest.fixture()
def editor_mcp(live_app):
    session = McpStdioSession(live_app.base_url, "editor", "editorPass123")
    yield session
    session.close()


@pytest.fixture()
def admin_mcp(live_app):
    session = McpStdioSession(live_app.base_url, "admin", "admin")
    yield session
    session.close()


class TestWhoAmI:
    def test_admin_role_is_detected(self, admin_mcp):
        result = admin_mcp.call_tool("whoami")
        assert result["role"] == "admin"

    def test_non_admin_role_is_reported_as_not_admin(self, viewer_mcp):
        result = viewer_mcp.call_tool("whoami")
        assert "not admin" in result["role"]


class TestListAndGetTools:
    def test_list_tools_filters_by_category(self, viewer_mcp):
        result = viewer_mcp.call_tool("list_tools", {"category": "embossing"})
        assert result
        assert all(t["category"] == "embossing" for t in result)

    def test_get_tool_by_id(self, viewer_mcp):
        tools = viewer_mcp.call_tool("list_tools", {})
        first_id = tools[0]["id"]
        result = viewer_mcp.call_tool("get_tool", {"tool_id": first_id})
        assert result["id"] == first_id

    def test_get_tool_missing_id_reports_not_found(self, viewer_mcp):
        result = viewer_mcp.call_tool("get_tool", {"tool_id": 10**9})
        assert result["error"] == "not_found"


class TestRoleEnforcementOverMcp:
    def test_read_only_add_tool_is_forbidden(self, viewer_mcp):
        result = viewer_mcp.call_tool("add_tool", {"name": "Should be forbidden", "category": "die"})
        assert result["error"] == "forbidden"

    def test_read_write_can_add_and_delete(self, editor_mcp):
        created = editor_mcp.call_tool(
            "add_tool", {"name": "MCP protocol test tool", "category": "die", "client": "Protocol Test"}
        )
        assert created["success"] is True
        tool_id = created["tool"]["id"]

        deleted = editor_mcp.call_tool("delete_tool", {"tool_id": tool_id})
        assert deleted["success"] is True

        result = editor_mcp.call_tool("get_tool", {"tool_id": tool_id})
        assert result["error"] == "not_found"

    def test_update_tool_only_changes_given_fields(self, editor_mcp):
        created = editor_mcp.call_tool(
            "add_tool",
            {"name": "MCP update test tool", "category": "die", "client": "Original Client", "notes": "original notes"},
        )
        tool_id = created["tool"]["id"]
        try:
            updated = editor_mcp.call_tool("update_tool", {"tool_id": tool_id, "client": "New Client"})
            assert updated["success"] is True

            result = editor_mcp.call_tool("get_tool", {"tool_id": tool_id})
            assert result["client"] == "New Client"
            assert result["notes"] == "original notes"  # untouched field survives the partial update
        finally:
            editor_mcp.call_tool("delete_tool", {"tool_id": tool_id})
