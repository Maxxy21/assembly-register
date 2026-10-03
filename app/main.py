from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import routes_admin_api, routes_admin_ui, routes_public
from app.auth import LoginRequired
from app.db import get_db

app = FastAPI(title="Assembly Register", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(routes_public.router)
app.include_router(routes_admin_api.router)
app.include_router(routes_admin_ui.router)

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("Content-Security-Policy", CSP)
    # The check-in token is in the URL; never leak it to another site.
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("X-Robots-Tag", "noindex, nofollow")
    if not request.url.path.startswith("/static/"):
        h.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(LoginRequired)
async def login_required(request: Request, exc: LoginRequired):
    return RedirectResponse("/admin/ui/login", status_code=303)


@app.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/admin/ui", status_code=303)
