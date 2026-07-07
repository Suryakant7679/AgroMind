# MCP Setup For AgroMind

This project is now a good fit for MCP-assisted development because it has:

- FastAPI routes and Jinja UI that benefit from browser automation.
- Supabase auth, RLS, and `agent_memory` schema that benefit from database-aware tools.
- GitHub/Vercel deployment status that benefits from repository and CI/CD context.
- Agent workflows that should be tested with real app state, not only static code reads.

Do not commit real tokens or personal MCP client files. Use `.mcp.example.json` as a template only.

For the implementation checklist with tick marks, see `docs/mcp-roadmap.md`.

## Recommended Servers

### 1. Supabase MCP

Use for schema inspection, read-only database checks, migrations review, and verifying the new `agent_memory` table.

Recommended first configuration:

```json
{
  "mcpServers": {
    "supabase-readonly": {
      "type": "http",
      "url": "https://mcp.supabase.com/mcp?project_ref=YOUR_SUPABASE_PROJECT_REF&read_only=true"
    }
  }
}
```

Keep `read_only=true` for daily development. Remove it only when you intentionally want the assistant to apply migrations or modify database objects.

### 2. GitHub MCP

Use for issues, PRs, code browsing, action/deployment status, and release workflow context.

Remote configuration for MCP clients that support remote HTTP servers:

```json
{
  "servers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/"
    }
  }
}
```

For a local Docker setup with narrower permissions, use only the toolsets needed:

```bash
docker run -i --rm ^
  -e GITHUB_PERSONAL_ACCESS_TOKEN=YOUR_TOKEN ^
  -e GITHUB_TOOLSETS="repos,issues,pull_requests,actions,code_security" ^
  ghcr.io/github/github-mcp-server
```

### 3. Playwright MCP

Use for UI flows:

- `/login`
- `/dashboard`
- `/agents`
- tool submission
- voice/agent chat widget checks

Standard config:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"]
    }
  }
}
```

### 4. Filesystem MCP

Use for controlled local file reads/edits by MCP clients. Scope it only to this repo:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "cmd",
      "args": [
        "/c",
        "npx",
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "C:\\Users\\surya\\OneDrive\\Desktop\\AgroMind"
      ]
    }
  }
}
```

### 5. Git MCP

Use for repository history, branch-aware diffs, and local Git inspection. Keep it scoped to this repo.

```json
{
  "mcpServers": {
    "git": {
      "command": "uvx",
      "args": [
        "mcp-server-git",
        "--repository",
        "C:\\Users\\surya\\OneDrive\\Desktop\\AgroMind"
      ]
    }
  }
}
```

### 6. Fetch MCP

Use for controlled documentation lookups, such as provider docs, API references, and deployment docs.

```json
{
  "mcpServers": {
    "fetch": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "@modelcontextprotocol/server-fetch"]
    }
  }
}
```

### 7. Memory MCP

Useful for the development assistant's long-running project notes. This is separate from AgroMind's app-level `agent_memory` table.

```json
{
  "mcpServers": {
    "memory": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "@modelcontextprotocol/server-memory"]
    }
  }
}
```

### 8. AgroMind Agriculture MCP

Local project MCP server for agriculture agents. It starts with environmental context, crop calendar guidance, and mandi-price guidance.

```json
{
  "mcpServers": {
    "agromind-agriculture": {
      "command": "python",
      "args": ["-m", "agromind.mcp_servers.agriculture"]
    }
  }
}
```

## Suggested Priority

1. Supabase MCP, read-only and project-scoped.
2. Playwright MCP for UI verification.
3. GitHub MCP for deployment/PR context.
4. Filesystem and Git MCP for local code context if your MCP client lacks native repo access.
5. Fetch MCP for documentation.
6. Memory MCP for assistant continuity.
7. AgroMind Agriculture MCP for Farmer Agent domain tools.

## Security Rules For This Project

- Use project-scoped Supabase URLs.
- Prefer read-only database access by default.
- Never put Supabase service role keys, GitHub PATs, or OAuth secrets in committed MCP config.
- Avoid broad filesystem roots. Use only `C:\Users\surya\OneDrive\Desktop\AgroMind`.
- Do not enable Gmail/X/Google Drive MCP servers until OAuth scopes and approval workflows are reviewed.
- Keep external-action execution inside AgroMind's existing approve-before-run workflow.

## Codex Config Example

Codex normally reads MCP server config from your user-level config, not from this repo. Copy only the servers you want into your local Codex config:

```toml
[mcp_servers.playwright]
command = "npx"
args = ["@playwright/mcp@latest"]

[mcp_servers.filesystem]
command = "cmd"
args = ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\surya\\OneDrive\\Desktop\\AgroMind"]

[mcp_servers.git]
command = "uvx"
args = ["mcp-server-git", "--repository", "C:\\Users\\surya\\OneDrive\\Desktop\\AgroMind"]
```

For Supabase and GitHub remote MCP, use your MCP client's remote HTTP server support and OAuth flow where available.

## First Operational Checklist

1. Add Supabase MCP with `project_ref` and `read_only=true`.
2. Confirm the `agent_memory` table exists after running `supabase/schema.sql`.
3. Add Playwright MCP.
4. Test `/agents` with a logged-in user.
5. Add GitHub MCP after OAuth or token permissions are clear.
6. Keep write-capable database and GitHub tools disabled until a specific task needs them.
