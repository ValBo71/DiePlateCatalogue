"""MCP server for the Die & Plate Catalogue.

Exposes the catalogue's tool inventory to an MCP client (Claude Code, Claude Desktop, ...) as a
fixed set of tools, calling the app's existing /api/tools endpoints. One running server instance
is logged in as one user for its whole lifetime (see client.CatalogCredentials.from_env), so its
role - admin, read_write or read_only - is fixed at startup, not something the calling agent can
change. An action the role does not allow surfaces as the app's own 403, not a silent no-op.

Configure one server entry per role you want an agent to have, e.g. in Claude Code / Desktop's MCP
config:

    "catalog-viewer": {
      "command": "python",
      "args": ["mcp_server/server.py"],
      "env": {"CATALOG_USERNAME": "viewer", "CATALOG_PASSWORD": "...", "CATALOG_BASE_URL": "http://127.0.0.1:5050"}
    }
"""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from client import CatalogApiError, CatalogClient, CatalogCredentials

mcp = MCPServer("dieplate-catalogue")
_client: CatalogClient | None = None


def _get_client() -> CatalogClient:
    global _client
    if _client is None:
        _client = CatalogClient(CatalogCredentials.from_env())
    return _client


def _call(fn, *args, **kwargs) -> Any:
    """Runs an API call and turns a CatalogApiError into a message the model can read and act on,
    instead of an unhandled exception."""
    try:
        return fn(*args, **kwargs)
    except CatalogApiError as exc:
        if exc.status_code == 403:
            return {"error": "forbidden", "detail": exc.message, "hint": "the logged-in role does not allow this action"}
        return {"error": f"http_{exc.status_code}" if exc.status_code else "connection_error", "detail": exc.message}


@mcp.tool()
def whoami() -> dict:
    """Report the app account this MCP server is logged in as, and its role.

    Call this first in a session to know what the current role is allowed to do before
    attempting a write.
    """
    client = _get_client()
    # The app has no dedicated "who am I" endpoint; /account renders HTML for a human, so instead
    # infer the role from whether the admin-only /api/users endpoint is reachable.
    try:
        client.get("/api/users")
        return {"role": "admin"}
    except CatalogApiError as exc:
        if exc.status_code == 403:
            return {"role": "read_write or read_only (not admin) - exact role is not exposed by the app's API"}
        raise


@mcp.tool()
def list_tools(
    category: str | None = None,
    status: str | None = None,
    search: str | None = None,
    dimension: str | None = None,
) -> Any:
    """List tools in the catalogue (cutting dies, embossing plates, hot-foil plates).

    Args:
        category: "die", "embossing" or "foil". Omit for all categories.
        status: "active", "borrowed" or "archived". Omit for all statuses.
        search: free-text search across code, name, client, location, notes, dimensions and file path.
        dimension: matches against the tool's single-item or sheet dimensions (e.g. "90x90").
    """
    params = {}
    if category:
        params["category"] = category
    if status:
        params["status"] = status
    if search:
        params["q"] = search
    if dimension:
        params["dim"] = dimension
    return _call(_get_client().get, "/api/tools", params)


@mcp.tool()
def get_tool(tool_id: int) -> Any:
    """Get a single tool by id, including its attached drawings.

    The app has no single-item GET endpoint, so this filters the full list by id -
    acceptable at the catalogue's current size (dozens, not thousands, of tools).
    """
    tools = _call(_get_client().get, "/api/tools")
    if isinstance(tools, dict):  # an error dict from _call
        return tools
    match = next((t for t in tools if t["id"] == tool_id), None)
    return match if match is not None else {"error": "not_found", "detail": f"no tool with id {tool_id}"}


@mcp.tool()
def add_tool(
    name: str,
    category: str,
    client: str = "",
    dimensions: str = "",
    location: str = "",
    status: str = "active",
    notes: str = "",
    die_shape: str = "",
    die_type: str = "",
    material: str = "",
    single_item_dimensions: str = "",
    ups: int = 1,
    code: str = "",
) -> Any:
    """Add a new tool to the catalogue. Requires the admin or read_write role.

    Args:
        name: required.
        category: required; one of "die", "embossing", "foil".
        code: optional manual code (e.g. "SH-0099"); auto-generated per category if omitted.
        status: one of "active", "borrowed", "archived" (default "active").
        die_shape: for dies only, e.g. "box", "circle", "oval", "folder", "envelope", "label", "playing_cards".
        die_type: for dies only, e.g. "flat", "cylindrical", "plunger".
        ups: number of copies of the tool on the plate/sheet (default 1).
    """
    data = {
        "name": name,
        "category": category,
        "client": client,
        "dimensions": dimensions,
        "location": location,
        "status": status,
        "notes": notes,
        "die_shape": die_shape,
        "die_type": die_type,
        "material": material,
        "single_item_dimensions": single_item_dimensions,
        "ups": str(ups),
        "code": code,
    }
    return _call(_get_client().post_form, "/api/tools", data)


@mcp.tool()
def update_tool(
    tool_id: int,
    name: str | None = None,
    category: str | None = None,
    client: str | None = None,
    dimensions: str | None = None,
    location: str | None = None,
    status: str | None = None,
    notes: str | None = None,
    die_shape: str | None = None,
    die_type: str | None = None,
    material: str | None = None,
    single_item_dimensions: str | None = None,
    ups: int | None = None,
) -> Any:
    """Update an existing tool. Requires the admin or read_write role.

    Only the fields you pass are changed; call get_tool first if you need to know the current
    values of the fields you are not changing (the app's PUT expects the full record).
    """
    current = get_tool(tool_id)
    if isinstance(current, dict) and "error" in current:
        return current

    updated = {
        "code": current["code"],
        "name": name if name is not None else current["name"],
        "category": category if category is not None else current["category"],
        "client": client if client is not None else current["client"],
        "dimensions": dimensions if dimensions is not None else current["dimensions"],
        "location": location if location is not None else current["location"],
        "status": status if status is not None else current["status"],
        "notes": notes if notes is not None else current["notes"],
        "die_shape": die_shape if die_shape is not None else current["die_shape"],
        "die_type": die_type if die_type is not None else current["die_type"],
        "material": material if material is not None else current["material"],
        "single_item_dimensions": single_item_dimensions if single_item_dimensions is not None else current["single_item_dimensions"],
        "ups": str(ups if ups is not None else current["ups"]),
    }
    return _call(_get_client().put_form, f"/api/tools/{tool_id}", updated)


@mcp.tool()
def delete_tool(tool_id: int) -> Any:
    """Delete a tool by id, including its attached drawings. Requires the admin or read_write role.

    This is irreversible - there is no undo in the app itself.
    """
    return _call(_get_client().delete, f"/api/tools/{tool_id}")


if __name__ == "__main__":
    mcp.run()
