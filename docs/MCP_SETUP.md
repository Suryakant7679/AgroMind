# MCP tools for AI Tutor

## What was added

| Server | Useful tools | Purpose | Status |
| --- | --- | --- | --- |
| [Microsoft Playwright](https://github.com/microsoft/playwright-mcp) | `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_take_screenshot` | Exercise signup, chat, attachments, responsive layouts and accessibility snapshots in a real browser. | Installed locally at 0.0.80; initialization and a browser smoke test passed. |
| [Context7](https://github.com/upstash/context7) | `resolve-library-id`, `query-docs` | Retrieve current library documentation for coding lessons and maintenance. | Installed locally at 4.1.0; initialization and the backend bridge passed. Remote documentation queries were not verified; an API key may be needed for applicable limits. |
| [Tavily](https://docs.tavily.com/documentation/mcp) | Search and page extraction | Research-backed lessons with source URLs. | Optional remote connection configured in VS Code; requires your Tavily API key. Not connected or called. |
| Existing AI Tutor DuckDuckGo | `duckduckgo_search` | Public web search from tutor chat. | Fixed the missing dispatcher registration; no additional package/key is required. Live search availability depends on DuckDuckGo. |

Versions are pinned in `package.json` / `package-lock.json`. Node dependencies are development tools and are excluded from the Python production Docker image.

## Use in VS Code

The workspace configuration is `.vscode/mcp.json`. Open the MCP server list in VS Code and start the server you want. The client may present its normal server-trust prompt. Tavily prompts for a password-style API-key input; no key is committed to the repository.

On another machine, install the same versions and verify the protocol handshake:

```powershell
npm.cmd ci
python scripts/check_mcp.py
```

Playwright uses a headless isolated browser session and expects an installed supported browser. Chrome was available and tested on this machine. It retains browser state while the IDE keeps that MCP process alive.

Example requests to your IDE assistant:

- "Use Playwright to test signup, send a chat message, and check the layout at mobile width."
- "Use Context7 to find the current Qdrant Python client filtering API."
- "Use Tavily to find primary sources for this lesson and include source links."

These are project/IDE integrations. Installing them does not automatically grant this running assistant session new tools or add student-facing buttons to the website.

## Use Context7 through the existing backend bridge

`mcp-servers.json` registers the installed Context7 entry point. The bridge remains opt-in, and server-resource MCP operations require an authenticated administrator. To enable it for a local administrative session, run from the project root:

```powershell
$env:AIOS_MCP_CUSTOM_ENABLED = "true"
python -m app.main
```

Use an existing account whose persisted roles include `admin`. `AIOS_ADMIN_EMAILS` assigns that role during registration; changing the variable does not retroactively change existing users.

Then send these chat requests in sequence:

```text
use custom MCP custom_tools {"server":"context7"}
use custom MCP custom_call {"server":"context7","tool":"resolve-library-id","arguments":{"libraryName":"qdrant-client","query":"How do I filter a vector search by user_id?"}}
```

Use the returned library ID with `query-docs`. Do not invent a library ID. These lookups send the supplied query to the external documentation provider. The checked-in backend bridge config intentionally contains only Context7 because the current bridge restarts each process per call and cannot preserve a Playwright browser session.

A normal authenticated tutor user can run the repaired built-in search without administrative access:

```text
use duckduckgo MCP duckduckgo_search {"query":"Khan Academy quadratic equations","max_results":3}
```

Tavily is currently an optional IDE connection. Adding it as the tutor's automatic research provider needs a backend adapter and an API key; the existing automatic research path still uses DuckDuckGo.
