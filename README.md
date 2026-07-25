# AgroMind AI

A multi-domain AI assistant platform for agriculture, healthcare, and education.

Live app:

```txt
https://agromind-six.vercel.app
```

## Tech Stack

- FastAPI for the web app and API routes
- Jinja2 templates for server-rendered pages
- Plain CSS for the interface
- Supabase for auth and persistence
- Groq and Gemini integrations
- python-pptx for PowerPoint export

## Domains

- Agriculture AI: plant health inspection, crop recommendation, farming chat, farm tools, learning guides.
- Healthcare AI: symptom checker, skin analyzer, medicine guidance, health chat, report analyzer.
- Education AI: lecture material generator, MCQ generator, worksheets, PPT generation, tutor chat, essay grading, YouTube learning.

Healthcare tools include:

```txt
This AI system does not replace professional doctors.
```

## Folder Structure

```txt
agromind/
  main.py              FastAPI routes
  ai.py                Groq/Gemini response generation
  data.py              Domain and tool definitions
  prompts.py           Prompt builders
  supabase_store.py    Supabase database helpers
  chatbot.py           Workspace chatbot with saved-output context
  static/styles.css    Plain CSS
  templates/           Jinja HTML pages
supabase/schema.sql    Existing database schema
requirements.txt       Python dependencies
run.py                 Local dev runner
```

## Environment

The app still reads `.env.local`, so your existing environment file can stay.

```bash
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash-lite
SESSION_SECRET=change-this-for-production
ALLOW_DEMO_LOGIN=false
```

If no provider key is configured, the AI route returns a structured fallback response so the UI remains testable.

## Supabase Setup

The database is unchanged. Run `supabase/schema.sql` in your Supabase SQL editor if you have not already done so.

Tables used:

- `profiles`
- `ai_outputs`
- `usage_events`
- `subscriptions`

For server-side inserts, set `SUPABASE_SERVICE_ROLE_KEY` in `.env.local`.

## Development

Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
python run.py
```

Open:

```txt
http://127.0.0.1:8000
```


### Integrated AI Tutor chatbot

AgroMind can embed the independent `AI tutor` project without copying or
modifying it. Set:

```txt
AI_TUTOR_ROOT=../AI tutor
AI_TUTOR_URL=http://127.0.0.1:8010
```

Then launch both applications:

```bash
python run_integrated.py
```

AgroMind runs on port `8000` and AI Tutor runs on port `8010`. Because AgroMind
loads the separately running AI Tutor service, changes made in the AI Tutor
project are reflected after its server is restarted. Configure `DATABASE_URL`
and `AIOS_STORAGE_BACKEND=postgres` in AI Tutor itself; AgroMind continues to
use Supabase for its own authentication and application data.

## Production

The project is configured for Vercel with:

- `api/index.py`
- `vercel.json`
- `.vercelignore`

Production URL:

```txt
https://agromind-six.vercel.app
```

Start command for other Python hosting platforms:

```bash
uvicorn agromind.main:app --host 0.0.0.0 --port $PORT
```

The included `Procfile` uses the same command.

Set a strong random value for:

```bash
SESSION_SECRET=
ENVIRONMENT=production
ALLOW_DEMO_LOGIN=false
```

In production, the app refuses to start with the default development session secret.

## Main Routes

```txt
/                         Home
/dashboard                Tool dashboard
/dashboard/{domain}       Domain page
/dashboard/{domain}/{tool} Tool workbench
/chatbot                  Workspace chatbot with recent tool/output context
/analytics                Analytics
/admin                    Admin
/profile                  Profile
/settings                 Settings
/pricing                  Plans
/login                    Login
/signup                   Create Supabase user
/api/usage                JSON usage endpoint
/api/export/report        Export hook
/api/ppt                  PPTX generator
```

## Notes

- The frontend is now server-rendered Python/Jinja, so there is no React or Next.js runtime requirement.
- Supabase auth uses email/password with the Supabase anon key. Demo login is disabled unless `ALLOW_DEMO_LOGIN=true`.
- Signup does not auto-login users. It asks them to verify their email through Supabase before logging in.
- Dashboard, analytics, profile, settings, tools, and admin pages require login.
- Admin access is controlled by `profiles.role = 'admin'`.
- Forms use session-backed CSRF tokens.
- Supabase table persistence uses the service role key when available, otherwise it uses the logged-in user's access token with RLS.

## Tests

```bash
pytest
```
