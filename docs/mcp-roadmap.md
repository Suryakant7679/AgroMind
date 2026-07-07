# AgroMind Product Roadmap

Legend:

- [x] Done
- [>] Next
- [ ] Planned
- [hold] Not in current scope

## Current Direction

AgroMind is now kept intentionally simple:

- Tool workbenches generate and save outputs.
- `/agents` is a simple Farmer/Doctor/Tutor chat with routing, memory, and local knowledge.
- `/chatbot` is a separate workspace chatbot that understands recent user tool usage and saved outputs.
- MCP files are optional development/domain helpers, not automatic live tool-calling inside the chatbot.

## Delivery Timeline

| Status | Target | Estimated time | What must be completed |
|---|---|---:|---|
| [>] | Demo-ready MVP polish | 2-4 days | Test login/signup, tool generation, `/agents`, `/chatbot`, exports, action drafts, and production deploys |
| [ ] | Strong production version | 2-3 weeks | Harden auth, payments, monitoring, admin diagnostics, action approvals, and real-user testing |
| [ ] | Full serious product | 4-6 weeks | Add reliable external data sources, compliance review, analytics, exports, and support workflows |

## Done In Current App

| Status | Area | Current implementation |
|---|---|---|
| [x] | Core web app | FastAPI, Jinja templates, Supabase auth/database, Vercel deployment |
| [x] | AI providers | Groq primary, Gemini fallback where supported; no OpenAI API key required |
| [x] | Tool workbenches | Agriculture, healthcare, and education tools save outputs to Supabase |
| [x] | Usage tracking | `usage_events`, analytics page, provider/domain summaries |
| [x] | Agent chat | `/agents` with Farmer/Doctor/Tutor routing, memory, and local markdown knowledge |
| [x] | Workspace chatbot | `/chatbot` uses recent `ai_outputs`, `usage_events`, and its own `agent_memory` context |
| [x] | Approval-based actions | Draft flow for Google Sheets, Gmail, and X actions |
| [x] | MCP templates | Supabase, GitHub, Playwright, Filesystem, Fetch, Memory, and local domain MCP examples |
| [x] | Local domain MCP servers | Agriculture, health evidence, and education servers exist for optional MCP clients/tests |

## Next MVP Tasks

| Status | Task | Notes |
|---|---|---|
| [>] | Verify Supabase production schema | Run `supabase/schema.sql`; confirm `agent_memory`, action drafts/runs, and RLS policies exist |
| [>] | Test auth journey | Signup, email verification, login, logout, protected route redirects |
| [>] | Test tool output journey | Generate one output per domain, save history, view dashboard/analytics |
| [>] | Test workspace chatbot | Confirm it sees recent user tool outputs and maintains chat memory |
| [>] | Test agent chat | Confirm routing to Farmer/Doctor/Tutor and provider fallback behavior |
| [>] | Test action drafts | Create Google Sheets/Gmail/X drafts and confirm approval safety behavior |
| [>] | Clean UI copy | Make dashboard, agents, chatbot, settings, and roadmap language consistent |
| [>] | Production smoke test | Check `/`, `/login`, `/signup`, `/dashboard`, `/agents`, `/chatbot`, `/analytics` on Vercel |

## Planned Production Hardening

| Status | Task | Notes |
|---|---|---|
| [ ] | Monitoring | Add Sentry or equivalent for backend errors |
| [ ] | Payment verification | Re-test Razorpay/plan upgrade flow end to end |
| [ ] | Admin diagnostics | Add clearer status checks for Supabase, Groq, Gemini, uploads, and actions |
| [ ] | Better exports | Polish PDF/PPT outputs and saved report views |
| [ ] | OAuth connectors | Connect Gmail/X/Google APIs only with explicit user approval and scoped tokens |
| [ ] | Data retention controls | Add user-facing controls for saved outputs and chat memory |
| [ ] | Healthcare safety review | Strengthen disclaimers, escalation language, and non-diagnosis boundaries |

## Optional MCP Work

These are useful later, but they are not part of the simple live MVP right now.

| Status | MCP/server | Decision |
|---|---|---|
| [x] | Supabase MCP | Keep as read-only development helper |
| [x] | Playwright MCP | Keep for UI testing |
| [x] | GitHub MCP | Keep for repo/deployment context |
| [x] | Filesystem/Fetch/Memory MCP | Keep as optional local development helpers |
| [x] | AgroMind Agriculture MCP | Keep as optional domain helper and test target |
| [x] | AgroMind Health Evidence MCP | Keep as optional read-only safety helper and test target |
| [x] | AgroMind Education MCP | Keep as optional education helper and test target |
| [hold] | Automatic agent tool-calling | Removed from live app to keep behavior simple |
| [hold] | Manim/Matplotlib rendering MCP | Not needed for current MVP |
| [hold] | Weather/SoilGrids/Mandi live APIs | Add only after MVP is stable |
| [hold] | PubMed/OpenFDA/ClinicalTrials MCP | Add only after healthcare safety review |
| [hold] | Google Drive/Classroom MCP | Add only after OAuth and approval workflow review |

## Current Recommended Order

1. [x] Keep live agent chat simple.
2. [x] Add separate workspace chatbot with recent tool/output context.
3. [>] Verify production Supabase schema.
4. [>] Smoke-test core routes and logged-in workflows.
5. [>] Polish UI copy and remove confusing labels.
6. [ ] Add monitoring and production diagnostics.
7. [ ] Re-test billing and external-action approval flows.
8. [ ] Decide which optional MCP/data integration is actually worth adding next.

## Notes

- `.mcp.example.json` is a template, not a secret-bearing runtime file.
- Local MCP servers are not automatically called by `/agents` or `/chatbot`.
- `/chatbot` understands tool usage from saved outputs and usage events.
- Keep Supabase MCP read-only unless a migration task explicitly needs write access.
- For healthcare, prefer safe educational guidance; do not allow autonomous diagnosis or prescription.
- External writes must stay draft-first and user-approved.
