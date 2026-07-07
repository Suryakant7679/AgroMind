# AgroMind MCP Roadmap

Legend:

- ✅ Added in this project template/docs
- 🔜 Next to implement or configure
- ⬜ Planned
- ⚠️ Use only after security review

## Phase 1: Core Development MCP Servers

| Status | MCP server | Purpose in AgroMind | Project status |
|---|---|---|---|
| ✅ | Supabase MCP | Inspect schema, RLS, `agent_memory`, user data, usage rows | Added to `.mcp.example.json` as `supabase-readonly` |
| ✅ | Playwright MCP | Test `/login`, `/dashboard`, `/agents`, tool forms, UI flows | Added to `.mcp.example.json` |
| ✅ | GitHub MCP | Repo, PRs, issues, deployment checks, code security context | Added to `.mcp.example.json` |
| ✅ | Filesystem MCP | Controlled local repo file access | Added to `.mcp.example.json`, scoped to this repo |
| ✅ | Fetch MCP | Documentation and API reference lookup | Added to `.mcp.example.json` |
| ✅ | Memory MCP | Assistant-side development memory | Added to `.mcp.example.json` |

## Phase 2: Agriculture Agent MCP Servers

| Status | MCP server | Purpose in AgroMind | Suggested tools |
|---|---|---|---|
| ✅ | AgroMind Agriculture MCP | Local domain MCP server with initial agriculture tools | Added as `python -m agromind.mcp_servers.agriculture` in `.mcp.example.json` |
| ⬜ | Weather MCP | Weather-only server, preferably Open-Meteo backed | `forecast_by_location`, `rainfall_risk`, `heat_stress_risk` |
| ⬜ | SoilGrids MCP | Soil profile and pH/nitrogen/organic-carbon lookup | `soil_profile`, `soil_constraints`, `crop_soil_match` |
| ⬜ | Market Price MCP | Mandi/commodity pricing from Data.gov.in or curated source | `mandi_price`, `price_trend`, `sell_or_hold_signal` |
| ⬜ | Maps/Geocoding MCP | Convert village/city/coordinates for weather and soil tools | `geocode`, `reverse_geocode`, `nearby_markets` |

## Phase 3: Healthcare Agent MCP Servers

| Status | MCP server | Purpose in AgroMind | Suggested tools |
|---|---|---|---|
| ✅ | AgroMind Health Evidence MCP | Read-only medical evidence and safety lookup | Added as `python -m agromind.mcp_servers.health` in `.mcp.example.json` |
| ⬜ | PubMed/NCBI MCP | Research lookup for Doctor Agent | `search_pubmed`, `summarize_abstracts` |
| ⬜ | OpenFDA/RxNorm MCP | Drug labels, warnings, adverse events, medication normalization | `drug_label`, `drug_warnings`, `normalize_drug_name` |
| ⬜ | ClinicalTrials MCP | Trial lookup for education/research only | `search_trials`, `trial_summary` |
| ⚠️ | EHR/FHIR MCP | Real patient record workflows | Use only with explicit compliance and auth controls |

## Phase 4: Education Agent MCP Servers

| Status | MCP server | Purpose in AgroMind | Suggested tools |
|---|---|---|---|
| ✅ | AgroMind Education MCP | YouTube learning, notes, quiz, revision workflows | Added as `python -m agromind.mcp_servers.education` in `.mcp.example.json` |
| ⬜ | Google Drive MCP | Store/read lesson plans, worksheets, reports | `search_docs`, `save_doc`, `read_doc` |
| ⬜ | Google Classroom MCP | Classroom assignment workflows | `list_courses`, `create_assignment`, `post_material` |
| ⬜ | Knowledge Base MCP | Local curriculum and school notes RAG | `search_curriculum`, `retrieve_notes` |
| ⬜ | PDF/Document MCP | Parse uploaded worksheets/reports more deeply | `extract_pdf_text`, `summarize_document` |

## Phase 5: Action And Business MCP Servers

| Status | MCP server | Purpose in AgroMind | Safety rule |
|---|---|---|---|
| ⚠️ | Google Sheets MCP | Save farmer logs, admin exports, learning records | Draft first, user approves |
| ⚠️ | Gmail MCP | Send reports or summaries | Draft first, user approves |
| ⚠️ | X/Twitter MCP | Publish approved social posts | Draft first, user approves |
| ⬜ | Stripe MCP | Billing alternative or future payments | Keep payment actions scoped |
| ⬜ | Sentry MCP | Production error monitoring | Read-only first |
| ⬜ | Vercel MCP | Deployment/project diagnostics if available in your MCP client | Read-only first |

## Current Recommended Order

1. ✅ Add core server templates to the repo.
2. 🔜 Configure Supabase MCP with real `project_ref` in your local MCP client.
3. 🔜 Run `supabase/schema.sql` so `agent_memory` exists.
4. 🔜 Add Playwright MCP in your local MCP client and test `/agents`.
5. ✅ Build custom AgroMind Agriculture MCP.
6. ✅ Build custom AgroMind Health Evidence MCP.
7. ✅ Build custom AgroMind Education MCP.
8. 🔜 Add Google Drive/Sheets/Gmail only after approval workflow review.

## Notes

- `.mcp.example.json` is a template, not a secret-bearing runtime file.
- Keep Supabase read-only until a migration task explicitly needs write access.
- For healthcare, prefer read-only evidence retrieval; do not allow autonomous diagnosis, prescription, or patient-record writes.
- For external actions, keep AgroMind's existing approve-before-execute pattern.
