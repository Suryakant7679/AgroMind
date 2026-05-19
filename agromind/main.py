import io
import os
import secrets
from pathlib import Path
from urllib.parse import quote

import markdown
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pptx import Presentation
from pptx.util import Inches, Pt
from starlette.middleware.sessions import SessionMiddleware

from agromind.ai import AIProviderError, generate_ai_response
from agromind.data import DOMAINS, all_tools, get_domain, get_tool
from agromind.supabase_store import (
    fetch_profile,
    fetch_profiles,
    fetch_recent_outputs,
    insert_profile_if_missing,
    save_output,
    sign_in_with_password,
    sign_up_with_password,
    supabase_auth_configured,
    supabase_client,
    supabase_database_configured,
)

load_dotenv(".env.local")
load_dotenv()

DEFAULT_DEV_SECRET = "agromind-dev-secret"
BASE_DIR = Path(__file__).resolve().parent
session_secret = os.getenv("SESSION_SECRET", DEFAULT_DEV_SECRET)
if os.getenv("ENVIRONMENT", "").lower() == "production" and session_secret == DEFAULT_DEV_SECRET:
    raise RuntimeError("Set a strong SESSION_SECRET before running in production.")

app = FastAPI(title="AgroMind AI")
app.add_middleware(SessionMiddleware, secret_key=session_secret, https_only=os.getenv("ENVIRONMENT", "").lower() == "production")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def user_from_session(request: Request) -> dict | None:
    return request.session.get("user")


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify_csrf(request: Request, token: str | None) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not token or not secrets.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")


def safe_next(path: str) -> str:
    if not path.startswith("/") or path.startswith("//"):
        return "/dashboard"
    return path


def login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)


def require_user(request: Request) -> dict | RedirectResponse:
    user = user_from_session(request)
    if not user:
        return login_redirect(request)
    return user


def require_admin(request: Request) -> tuple[dict, dict] | RedirectResponse:
    user_or_response = require_user(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response

    profile = fetch_profile(user_or_response.get("id"), user_or_response.get("access_token"))
    if not profile or profile.get("role") != "admin":
        return RedirectResponse("/dashboard", status_code=303)
    return user_or_response, profile


def page(request: Request, template: str, **context):
    base = {"request": request, "domains": DOMAINS, "user": user_from_session(request), "csrf_token": csrf_token(request)}
    base.update(context)
    return templates.TemplateResponse(request, template, base)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return page(request, "home.html", tools=all_tools())


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user_or_response = require_user(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    recent = fetch_recent_outputs(user_or_response.get("id"), access_token=user_or_response.get("access_token"))
    return page(request, "dashboard.html", tools=all_tools(), recent=recent)


@app.get("/dashboard/{domain_id}", response_class=HTMLResponse)
def domain_page(request: Request, domain_id: str):
    user_or_response = require_user(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    domain = get_domain(domain_id)
    if not domain:
        return RedirectResponse("/dashboard", status_code=303)
    return page(request, "domain.html", domain=domain)


@app.get("/dashboard/{domain_id}/{tool_id}", response_class=HTMLResponse)
def tool_page(request: Request, domain_id: str, tool_id: str):
    user_or_response = require_user(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    domain = get_domain(domain_id)
    tool = get_tool(domain_id, tool_id)
    if not domain or not tool:
        return RedirectResponse("/dashboard", status_code=303)
    return page(request, "tool.html", domain=domain, tool=tool, output_html=None, fields={})


@app.post("/dashboard/{domain_id}/{tool_id}", response_class=HTMLResponse)
async def run_tool(request: Request, domain_id: str, tool_id: str, asset: UploadFile | None = File(default=None)):
    user_or_response = require_user(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    domain = get_domain(domain_id)
    tool = get_tool(domain_id, tool_id)
    if not domain or not tool:
        return RedirectResponse("/dashboard", status_code=303)

    form = await request.form()
    verify_csrf(request, str(form.get("csrf_token", "")))
    fields = {field["name"]: str(form.get(field["name"], "")) for field in tool["fields"]}
    try:
        output, provider = await generate_ai_response(domain_id, tool_id, fields, asset)
        save_output(
            user_or_response.get("id"),
            domain_id,
            tool_id,
            fields,
            output,
            provider,
            user_or_response.get("access_token"),
        )
        output_html = markdown.markdown(output, extensions=["tables", "fenced_code"])
        error = None
    except AIProviderError as exc:
        output_html = None
        error = exc.user_message
    except Exception as exc:
        output_html = None
        error = str(exc)
    return page(request, "tool.html", domain=domain, tool=tool, output_html=output_html, fields=fields, error=error)


@app.get("/analytics", response_class=HTMLResponse)
def analytics(request: Request):
    user_or_response = require_user(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    rows = [
        ("Agriculture", "1,284", "42%", "Plant inspections"),
        ("Healthcare", "932", "31%", "Symptom checks"),
        ("Education", "1,621", "54%", "MCQ generation"),
    ]
    return page(request, "analytics.html", rows=rows)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    admin_or_response = require_admin(request)
    if isinstance(admin_or_response, RedirectResponse):
        return admin_or_response
    users = fetch_profiles()
    return page(request, "admin.html", users=users)


@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    user_or_response = require_user(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    profile_data = fetch_profile(user_or_response.get("id"), user_or_response.get("access_token"))
    return page(request, "profile.html", profile=profile_data)


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    user_or_response = require_user(request)
    if isinstance(user_or_response, RedirectResponse):
        return user_or_response
    configured = {
        "supabase_auth": supabase_auth_configured(),
        "supabase_database": supabase_database_configured(),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
    }
    return page(request, "settings.html", configured=configured)


@app.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request):
    return page(request, "pricing.html")


@app.get("/login", response_class=HTMLResponse)
def login(request: Request, next: str = "/dashboard"):
    return page(request, "login.html", next=safe_next(next), message=None)


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(""),
    csrf_token: str = Form(...),
    next: str = Form("/dashboard"),
):
    verify_csrf(request, csrf_token)
    next = safe_next(next)
    if supabase_auth_configured():
        if not password:
            return page(request, "login.html", next=next, message="Password is required.")
        try:
            request.session["user"] = sign_in_with_password(email, password)
            return RedirectResponse(next, status_code=303)
        except Exception:
            return page(request, "login.html", next=next, message="Login failed. Check your email and password.")

    if os.getenv("ALLOW_DEMO_LOGIN", "").lower() == "true":
        request.session["user"] = {"id": None, "email": email}
        return RedirectResponse(next, status_code=303)

    return page(
        request,
        "login.html",
        next=next,
        message="Authentication is not configured. Add valid Supabase URL and anon key before signing in.",
    )


@app.get("/signup", response_class=HTMLResponse)
def signup(request: Request, next: str = "/dashboard"):
    return page(request, "signup.html", next=safe_next(next), message=None)


@app.post("/signup", response_class=HTMLResponse)
async def signup_submit(
    request: Request,
    full_name: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    next: str = Form("/dashboard"),
):
    verify_csrf(request, csrf_token)
    next = safe_next(next)
    if len(password) < 6:
        return page(request, "signup.html", next=next, message="Password must be at least 6 characters.")

    if not supabase_auth_configured():
        return page(request, "signup.html", next=next, message="Supabase auth is not configured.")

    try:
        user = sign_up_with_password(email, password, full_name)
        if user.get("id") and user.get("email"):
            insert_profile_if_missing(user["id"], user["email"], full_name)
        return page(
            request,
            "login.html",
            next=next,
            message="Account created. Check your email for the Supabase verification link, then log in.",
        )
    except Exception as exc:
        return page(request, "signup.html", next=next, message=str(exc))


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/api/usage")
def usage():
    return {
        "requestsToday": 2480,
        "monthlyLimit": 5000,
        "domains": {"agriculture": 1284, "healthcare": 932, "education": 1621},
    }


@app.post("/api/export/report")
async def export_report(request: Request, format: str = Form("pdf"), csrf_token: str = Form(...)):
    user_or_response = require_user(request)
    if isinstance(user_or_response, RedirectResponse):
        raise HTTPException(status_code=401, detail="Login required.")
    verify_csrf(request, csrf_token)
    return {"ok": True, "format": format, "message": "Server-side export hook is ready in Python."}


@app.post("/api/ppt")
async def create_ppt(
    request: Request,
    title: str = Form("AgroMind AI Presentation"),
    slides: str = Form(""),
    csrf_token: str = Form(...),
):
    user_or_response = require_user(request)
    if isinstance(user_or_response, RedirectResponse):
        raise HTTPException(status_code=401, detail="Login required.")
    verify_csrf(request, csrf_token)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    title_slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = title_slide.shapes.add_textbox(Inches(0.7), Inches(2.4), Inches(12), Inches(0.8))
    run = box.text_frame.paragraphs[0].add_run()
    run.text = title
    run.font.size = Pt(34)
    run.font.bold = True

    slide_items = [item.strip() for item in slides.splitlines() if item.strip()] or ["Overview", "Key concepts", "Examples", "Summary"]
    for index, item in enumerate(slide_items, start=1):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        heading = slide.shapes.add_textbox(Inches(0.7), Inches(0.6), Inches(11.5), Inches(0.5))
        heading.text_frame.text = f"{index}. {item}"
        body = slide.shapes.add_textbox(Inches(0.7), Inches(1.5), Inches(11), Inches(1.2))
        body.text_frame.text = "Use this slide for key points, examples, and supporting notes from the selected topic."

    output = io.BytesIO()
    prs.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": 'attachment; filename="agromind-presentation.pptx"'},
    )
