"""Tests against the Flask app's own /api/tools and /api/users endpoints - the same ones the web
UI calls. Each test that adds a tool cleans it up, so tests can run in any order without
accumulating state in the shared, session-scoped live_app database.
"""
from __future__ import annotations

import requests


def _tool_form(**overrides) -> dict:
    data = {
        "name": "Test tool",
        "category": "die",
        "client": "Test Client",
        "dimensions": "",
        "location": "",
        "status": "active",
        "notes": "",
        "die_shape": "",
        "die_type": "",
        "material": "",
        "single_item_dimensions": "",
        "ups": "1",
    }
    data.update(overrides)
    return data


class TestReadAccess:
    def test_list_tools_requires_login(self, live_app):
        response = requests.get(f"{live_app.base_url}/api/tools", timeout=10)
        assert response.status_code == 401

    def test_all_three_roles_can_list_tools(self, admin_session, editor_session, viewer_session, live_app):
        for session in (admin_session, editor_session, viewer_session):
            response = session.get(f"{live_app.base_url}/api/tools", timeout=10)
            assert response.status_code == 200
            assert isinstance(response.json(), list)

    def test_category_filter(self, admin_session, live_app):
        response = admin_session.get(f"{live_app.base_url}/api/tools", params={"category": "die"}, timeout=10)
        assert response.status_code == 200
        tools = response.json()
        assert tools  # the demo data has dies
        assert all(t["category"] == "die" for t in tools)

    def test_search_filter(self, admin_session, live_app):
        response = admin_session.get(f"{live_app.base_url}/api/tools", params={"q": "does-not-exist-xyz"}, timeout=10)
        assert response.status_code == 200
        assert response.json() == []


class TestReadOnlyRoleIsRestricted:
    def test_read_only_cannot_add_tool(self, viewer_session, live_app):
        response = viewer_session.post(
            f"{live_app.base_url}/api/tools",
            data=_tool_form(name="Should be forbidden"),
            headers={"Origin": live_app.base_url},
            timeout=10,
        )
        assert response.status_code == 403

    def test_read_only_cannot_delete_tool(self, viewer_session, editor_session, live_app):
        create = editor_session.post(
            f"{live_app.base_url}/api/tools",
            data=_tool_form(name="Temp tool for delete-permission check"),
            headers={"Origin": live_app.base_url},
            timeout=10,
        ).json()
        tool_id = create["tool"]["id"]
        try:
            response = viewer_session.delete(
                f"{live_app.base_url}/api/tools/{tool_id}", headers={"Origin": live_app.base_url}, timeout=10
            )
            assert response.status_code == 403
        finally:
            editor_session.delete(
                f"{live_app.base_url}/api/tools/{tool_id}", headers={"Origin": live_app.base_url}, timeout=10
            )

    def test_read_only_cannot_list_users(self, viewer_session, live_app):
        response = viewer_session.get(f"{live_app.base_url}/api/users", timeout=10)
        assert response.status_code == 403


class TestReadWriteCrudLifecycle:
    def test_add_update_delete_tool(self, editor_session, live_app):
        create_response = editor_session.post(
            f"{live_app.base_url}/api/tools",
            data=_tool_form(name="CRUD lifecycle tool", client="Lifecycle Client"),
            headers={"Origin": live_app.base_url},
            timeout=10,
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["success"] is True
        tool_id = created["tool"]["id"]
        tool_code = created["tool"]["code"]
        assert tool_code.startswith("SH-")

        try:
            listed = editor_session.get(
                f"{live_app.base_url}/api/tools", params={"q": "CRUD lifecycle tool"}, timeout=10
            ).json()
            assert any(t["id"] == tool_id for t in listed)

            # Unlike POST, PUT requires "code" in the form and rejects the request with 400 if it
            # is missing - the app expects the full record back, not a partial patch.
            update_response = editor_session.put(
                f"{live_app.base_url}/api/tools/{tool_id}",
                data=_tool_form(code=tool_code, name="CRUD lifecycle tool", client="Updated Client", status="borrowed"),
                headers={"Origin": live_app.base_url},
                timeout=10,
            )
            assert update_response.status_code == 200

            listed_after_update = editor_session.get(
                f"{live_app.base_url}/api/tools", params={"q": "CRUD lifecycle tool"}, timeout=10
            ).json()
            updated_tool = next(t for t in listed_after_update if t["id"] == tool_id)
            assert updated_tool["client"] == "Updated Client"
            assert updated_tool["status"] == "borrowed"
        finally:
            delete_response = editor_session.delete(
                f"{live_app.base_url}/api/tools/{tool_id}", headers={"Origin": live_app.base_url}, timeout=10
            )
            assert delete_response.status_code == 200

        remaining = editor_session.get(
            f"{live_app.base_url}/api/tools", params={"q": "CRUD lifecycle tool"}, timeout=10
        ).json()
        assert all(t["id"] != tool_id for t in remaining)

    def test_add_tool_rejects_invalid_category(self, editor_session, live_app):
        response = editor_session.post(
            f"{live_app.base_url}/api/tools",
            data=_tool_form(category="not-a-real-category"),
            headers={"Origin": live_app.base_url},
            timeout=10,
        )
        assert response.status_code == 400


class TestAdminOnlyUserManagement:
    def test_admin_can_list_users(self, admin_session, live_app):
        response = admin_session.get(f"{live_app.base_url}/api/users", timeout=10)
        assert response.status_code == 200
        usernames = {u["username"] for u in response.json()}
        assert {"admin", "editor", "viewer"}.issubset(usernames)

    def test_read_write_cannot_list_users(self, editor_session, live_app):
        response = editor_session.get(f"{live_app.base_url}/api/users", timeout=10)
        assert response.status_code == 403


class TestCsrfGuard:
    def test_cross_origin_write_is_rejected(self, admin_session, live_app):
        response = admin_session.post(
            f"{live_app.base_url}/api/tools",
            data=_tool_form(name="Should never be created"),
            headers={"Origin": "https://evil.example.com"},
            timeout=10,
        )
        assert response.status_code == 403
