# AgroMind MCP Roadmap

Legend:

- [x] Added in this project
- [>] Next to implement or configure
- [ ] Planned
- [!] Use only after security review

## Phase 1: Core Development MCP Servers

| Status | MCP server | Purpose in AgroMind | Project status |
|---|---|---|---|
| [x] | Supabase MCP | Inspect schema, RLS, `agent_memory`, user data, usage rows | Added to `.mcp.example.json` as `supabase-readonly` |
| [x] | Playwright MCP | Test `/login`, `/dashboard`, `/agents`, tool forms, UI flows | Added to `.mcp.example.json` |
| [x] | GitHub MCP | Repo, PRs, issues, deployment checks, code security context | Added to `.mcp.example.json` |
| [x] | Filesystem MCP | Controlled local repo file access | Added to `.mcp.example.json`, scoped to this repo |
| [x] | Fetch MCP | Documentation and API reference lookup | Added to `.mcp.example.json` |
| [x] | Memory MCP | Assistant-side development memory | Added to `.mcp.example.json` |

## Phase 2: Agriculture Agent MCP Servers

| Status | MCP server | Purpose in AgroMind | Suggested tools |
|---|---|---|---|
| [x] | AgroMind Agriculture MCP | Local domain MCP server with crop calendar and market guidance | `get_crop_calendar`, `get_mandi_price_guidance`, `get_environmental_context` |
| [x] | Agent tool routing | Farmer Agent can call local agriculture tools before answering | Added in `agromind.agents.tools` |
| [ ] | Weather MCP | Weather-only server, preferably Open-Meteo backed | `forecast_by_location`, `rainfall_risk`, `heat_stress_risk` |
| [ ] | SoilGrids MCP | Soil profile and pH/nitrogen/organic-carbon lookup | `soil_profile`, `soil_constraints`, `crop_soil_match` |
| [ ] | Market Price MCP | Mandi/commodity pricing from Data.gov.in or curated source | `mandi_price`, `price_trend`, `sell_or_hold_signal` |
| [ ] | Maps/Geocoding MCP | Convert village/city/coordinates for weather and soil tools | `geocode`, `reverse_geocode`, `nearby_markets` |

## Phase 3: Healthcare Agent MCP Servers

| Status | MCP server | Purpose in AgroMind | Suggested tools |
|---|---|---|---|
| [x] | AgroMind Health Evidence MCP | Read-only medical evidence and safety lookup | `lookup_lab_marker`, `lookup_drug_safety`, `get_symptom_red_flags` |
| [x] | Agent tool routing | Doctor Agent can call local health tools before answering | Added in `agromind.agents.tools` |
| [ ] | PubMed/NCBI MCP | Research lookup for Doctor Agent | `search_pubmed`, `summarize_abstracts` |
| [ ] | OpenFDA/RxNorm MCP | Drug labels, warnings, adverse events, medication normalization | `drug_label`, `drug_warnings`, `normalize_drug_name` |
| [ ] | ClinicalTrials MCP | Trial lookup for education/research only | `search_trials`, `trial_summary` |
| [!] | EHR/FHIR MCP | Real patient record workflows | Use only with explicit compliance and auth controls |

## Phase 4: Education Agent MCP Servers

| Status | MCP server | Purpose in AgroMind | Suggested tools |
|---|---|---|---|
| [x] | AgroMind Education MCP | YouTube learning, notes, quiz, revision, lesson workflows | `get_youtube_learning_context`, `create_quiz_plan`, `create_revision_plan`, `create_lesson_outline` |
| [x] | Education plotting tool | Plan classroom plots/graphs before rendering | `create_plot_plan` |
| [x] | Agent tool routing | Tutor Agent can call local education tools before answering | Added in `agromind.agents.tools` |
| [>] | Manim/Matplotlib Render MCP | Generate real chart images or lesson animations | `render_plot_image`, `render_manim_scene`, `export_visual_asset` |
| [ ] | Google Drive MCP | Store/read lesson plans, worksheets, reports | `search_docs`, `save_doc`, `read_doc` |
| [ ] | Google Classroom MCP | Classroom assignment workflows | `list_courses`, `create_assignment`, `post_material` |
| [ ] | Knowledge Base MCP | Local curriculum and school notes RAG | `search_curriculum`, `retrieve_notes` |
| [ ] | PDF/Document MCP | Parse uploaded worksheets/reports more deeply | `extract_pdf_text`, `summarize_document` |

## Phase 5: Action And Business MCP Servers

| Status | MCP server | Purpose in AgroMind | Safety rule |
|---|---|---|---|
| [!] | Google Sheets MCP | Save farmer logs, admin exports, learning records | Draft first, user approves |
| [!] | Gmail MCP | Send reports or summaries | Draft first, user approves |
| [!] | X/Twitter MCP | Publish approved social posts | Draft first, user approves |
| [ ] | Stripe MCP | Billing alternative or future payments | Keep payment actions scoped |
| [ ] | Sentry MCP | Production error monitoring | Read-only first |
| [ ] | Vercel MCP | Deployment/project diagnostics if available in your MCP client | Read-only first |

## Current Recommended Order

1. [x] Add core server templates to the repo.
2. [x] Build custom AgroMind Agriculture MCP.
3. [x] Build custom AgroMind Health Evidence MCP.
4. [x] Build custom AgroMind Education MCP.
5. [x] Wire local MCP-style tools into the live agent orchestrator.
6. [>] Configure Supabase MCP with real `project_ref` in your local MCP client.
7. [>] Run `supabase/schema.sql` so `agent_memory` exists.
8. [>] Add Playwright MCP in your local MCP client and test `/agents`.
9. [>] Add Manim/Matplotlib render MCP for real plot images/videos.
10. [ ] Add Google Drive/Sheets/Gmail only after approval workflow review.

## Notes

- `.mcp.example.json` is a template, not a secret-bearing runtime file.
- Keep Supabase read-only until a migration task explicitly needs write access.
- For healthcare, prefer read-only evidence retrieval; do not allow autonomous diagnosis, prescription, or patient-record writes.
- For external actions, keep AgroMind's existing approve-before-execute pattern.
- The local MCP servers are useful because they give AgroMind domain tools that can also be exposed to external MCP clients later.
