"""Member-facing check-in pages. The assembly comes from the service token."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app import register
from app.db import get_db
from app.models import Service
from app.templating import templates

router = APIRouter()


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _not_found(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "public/not_found.html", status_code=404)


def _closed(request: Request, service: Service, status_code: int = 200) -> HTMLResponse:
    now = register.utcnow()
    return templates.TemplateResponse(
        request,
        "public/closed.html",
        {
            "service": service,
            "assembly": service.assembly,
            "not_yet": now < service.opens_at,
        },
        status_code=status_code,
    )


@router.get("/s/{token}", response_class=HTMLResponse)
def check_in_page(
    request: Request,
    token: str,
    q: str = "",
    db: Session = Depends(get_db),
):
    service = register.service_by_token(db, token)
    if service is None:
        return _not_found(request)
    if not service.is_open(register.utcnow()):
        return _closed(request, service)
    # ?q= is the no-JavaScript fallback: the search form submits here and
    # the results come back as plain forms.
    q = q.strip()
    hits = (
        register.search_members(db, service, q)
        if len(q) >= register.SEARCH_MIN_CHARS
        else None
    )
    return templates.TemplateResponse(
        request,
        "public/check_in.html",
        {"service": service, "assembly": service.assembly, "q": q, "hits": hits},
    )


@router.get("/s/{token}/members")
def member_lookup(
    token: str,
    q: str = Query(min_length=register.SEARCH_MIN_CHARS, max_length=100),
    db: Session = Depends(get_db),
):
    service = register.service_by_token(db, token)
    if service is None:
        raise HTTPException(status_code=404, detail="Unknown check-in code")
    if not service.is_open(register.utcnow()):
        raise HTTPException(status_code=403, detail="Check-in is closed")
    hits = register.search_members(db, service, q.strip())
    return {
        "results": [
            {"id": str(h.id), "name": h.name, "checked_in": h.checked_in} for h in hits
        ]
    }


@router.post("/s/{token}/check-in")
def check_in(
    request: Request,
    token: str,
    member_id: str | None = Form(default=None),
    visitor_name: str | None = Form(default=None),
    visitor_phone: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    as_json = _wants_json(request)

    def fail(status: int, message: str):
        if as_json:
            return JSONResponse({"error": message}, status_code=status)
        service_ctx = {"service": service, "assembly": service.assembly} if service else {}
        return templates.TemplateResponse(
            request,
            "public/problem.html",
            {"message": message, **service_ctx},
            status_code=status,
        )

    service = register.service_by_token(db, token)
    if service is None:
        return JSONResponse({"error": "Unknown check-in code"}, 404) if as_json else _not_found(request)
    if not service.is_open(register.utcnow()):
        if as_json:
            return JSONResponse({"error": "Check-in is closed"}, status_code=403)
        return _closed(request, service, status_code=403)

    member_id = (member_id or "").strip()
    visitor_name = (visitor_name or "").strip()
    if bool(member_id) == bool(visitor_name):
        return fail(400, "Please choose your name, or fill in the visitor form.")

    try:
        if member_id:
            result = register.check_in_member(db, service, uuid.UUID(member_id))
        else:
            result = register.check_in_visitor(db, service, visitor_name, visitor_phone)
    except (ValueError, register.NotFound):
        return fail(404, "We couldn't find that name. Please ask an usher to add you.")

    if as_json:
        return {"status": "already" if result.already else "checked_in", "name": result.name}
    return templates.TemplateResponse(
        request,
        "public/done.html",
        {"service": service, "assembly": service.assembly, "result": result},
    )
