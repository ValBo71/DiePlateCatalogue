# Catalogue MCP server

An [MCP](https://modelcontextprotocol.io) server that exposes the Die & Plate Catalogue's tool
inventory to an MCP client (Claude Code, Claude Desktop, ...): list, search, add, update and
delete tools, through the app's own `/api/tools` endpoints - the same ones the web UI calls.

## Role model

The app enforces three roles (`admin`, `read_write`, `read_only`) on every request; see
`require_role` in `../app.py`. This server does not re-implement or check roles itself - it logs
in once, as one user, and forwards whatever the app answers. If that user's role does not allow
an action, the app answers `403` and the tool call reports that back to the model as an error, not
a crash.

Because the role is fixed for the whole life of the server process, run **one server instance per
role you want an agent to have** rather than one server that can act as anyone. A `read_only`
instance cannot add, update or delete a tool no matter what it is asked to do - the app refuses
the write before this server's code even runs.

## Setup

1. Install the app's own dependencies (`../requirements.txt`) and start it: `python ../app.py`.
   It listens on `http://127.0.0.1:5050` by default.
2. Create the users you want to expose, one per role, from `/admin` (as the bootstrap `admin`
   user - the demo database ships with `admin` / `admin`, see the root README). The demo
   database already includes two such accounts: `editor` / `editorPass123` (`read_write`) and
   `viewer` / `viewerPass123` (`read_only`) - change their passwords before relying on them for
   anything beyond trying this server out.
3. Install this server's dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Add one MCP server entry per role in your client's config, each with its own credentials:

   ```json
   {
     "mcpServers": {
       "catalog-viewer": {
         "command": "python",
         "args": ["mcp_server/server.py"],
         "env": {
           "CATALOG_BASE_URL": "http://127.0.0.1:5050",
           "CATALOG_USERNAME": "viewer",
           "CATALOG_PASSWORD": "..."
         }
       },
       "catalog-editor": {
         "command": "python",
         "args": ["mcp_server/server.py"],
         "env": {
           "CATALOG_BASE_URL": "http://127.0.0.1:5050",
           "CATALOG_USERNAME": "editor",
           "CATALOG_PASSWORD": "..."
         }
       }
     }
   }
   ```

   `CATALOG_BASE_URL` defaults to `http://127.0.0.1:5050` if omitted.

## Tools

| Tool | Roles that succeed | Notes |
|---|---|---|
| `whoami` | any | reports `admin` if the account can read `/api/users`, otherwise says it is not admin (the app has no dedicated "who am I" endpoint) |
| `list_tools` | any | filters: `category`, `status`, `search`, `dimension` |
| `get_tool` | any | fetches the full list and filters by id client-side |
| `add_tool` | `admin`, `read_write` | `read_only` gets a `forbidden` error |
| `update_tool` | `admin`, `read_write` | reads the current record first, so you only need to pass the fields you are changing |
| `delete_tool` | `admin`, `read_write` | irreversible; the app has no undo |

Out of scope for this first version: file upload/download (`copy-file`, `drawings/download`) and
user management (`/api/users`) - both touch the filesystem or account security more directly and
are left for a later iteration if needed.

## Tests

`../tests/test_mcp_client.py` and `../tests/test_mcp_protocol.py` cover this server - the second
drives it over a real MCP stdio JSON-RPC handshake, the same way an MCP host does. See the root
README's Tests section for how to run them.

## Note on the `mcp` SDK version

This server targets `mcp` 2.x, where the class used here was renamed from `FastMCP` to
`MCPServer` and moved from `mcp.server.fastmcp` to `mcp.server.mcpserver` (the old import raises a
`ModuleNotFoundError` with a migration pointer, which is how this was caught). If you see that
error, either update this file's import to match your installed SDK's migration guide, or pin
`mcp<2` in `requirements.txt` to keep the `FastMCP` API.
