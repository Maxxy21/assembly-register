"""Server-rendered admin pages. Plain forms, Post/Redirect/Get throughout."""

from __future__ import annotations

import uuid
from datetime import date, time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import register
from app.auth import COOKIE_NAME, assembly_for_token, require_admin_page
from app.config import settings
from app.db import get_db
from app.models import Assembly, Attendance, Service
from app.qr import qr_svg
from app.templating import templates

router = APIRouter(prefix="/admin/ui")


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _page(request: Request, name: str, assembly: Assembly | None, **ctx) -> HTMLResponse:
    status_code = ctx.pop("status_code", 200)
    return templates.TemplateResponse(
        request, f"admin/{name}", {"assembly": assembly, **ctx}, status_code=status_code
    )


def _service(db: Session, assembly: Assembly, service_id: uuid.UUID) -> Service:
    service = register.service_for_assembly(db, assembly, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


def _optional_time(value: str) -> time | None:
    return time.fromisoformat(value) if value.strip() else None


# --- sign in -----------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return _page(request, "login.html", None)


@router.post("/login")
def login(request: Request, token: str = Form(...), db: Session = Depends(get_db)):
    token = token.strip()
    if assembly_for_token(db, token) is None:
        return _page(request, "login.html", None, error="That token isn’t right.", status_code=401)
    response = _redirect("/admin/ui")
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=60 * 60 * 12,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/admin",
    )
    return response


@router.post("/logout")
def logout():
    response = _redirect("/admin/ui/login")
    response.delete_cookie(COOKIE_NAME, path="/admin")
    return response


# --- services ----------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def dashboard(
    request: Request,
    assembly: Assembly = Depends(require_admin_page),
    db: Session = Depends(get_db),
):
    return _page(
        request,
        "dashboard.html",
        assembly,
        services=register.list_services(db, assembly),
        next_sunday=register.next_sunday(assembly.timezone),
        default_opens=settings.default_opens.strftime("%H:%M"),
        default_closes=settings.default_closes.strftime("%H:%M"),
        now=register.utcnow(),
        retention_days=settings.retention_days,
        message=request.query_params.get("msg"),
    )


@router.post("/services")
def create_service(
    request: Request,
    service_date: date = Form(...),
    title: str = Form(""),
    opens: str = Form(""),
    closes: str = Form(""),
    assembly: Assembly = Depends(require_admin_page),
    db: Session = Depends(get_db),
):
    try:
        service = register.create_service(
            db, assembly, service_date, title, _optional_time(opens), _optional_time(closes)
        )
    except ValueError as exc:
        return _page(
            request,
            "dashboard.html",
            assembly,
            services=register.list_services(db, assembly),
            next_sunday=service_date,
            default_opens=opens,
            default_closes=closes,
            now=register.utcnow(),
            retention_days=settings.retention_days,
            error=str(exc),
            status_code=422,
        )
    return _redirect(f"/admin/ui/services/{service.id}")


@router.get("/services/{service_id}", response_class=HTMLResponse)
def service_detail(
    request: Request,
    service_id: uuid.UUID,
    assembly: Assembly = Depends(require_admin_page),
    db: Session = Depends(get_db),
):
    service = _service(db, assembly, service_id)
    url = register.check_in_url(service)
    attendance = register.attendance_for(db, service)
    present_ids = {a.member_id for a in attendance if a.member_id}
    addable = [
        m
        for m in register.list_members(db, assembly)
        if m.is_active and m.consent_at and m.id not in present_ids
    ]
    return _page(
        request,
        "service.html",
        assembly,
        service=service,
        url=url,
        qr=qr_svg(url),
        is_open=service.is_open(register.utcnow()),
        attendance=attendance,
        absentees=register.absentees_for(db, service),
        addable=addable,
        message=request.query_params.get("msg"),
    )


@router.post("/services/{service_id}/manual")
def manual_check_in(
    service_id: uuid.UUID,
    member_id: str = Form(""),
    visitor_name: str = Form(""),
    visitor_phone: str = Form(""),
    assembly: Assembly = Depends(require_admin_page),
    db: Session = Depends(get_db),
):
    """An usher adding someone by hand. Allowed outside the check-in window,
    so latecomers and people without a phone can still be counted."""
    service = _service(db, assembly, service_id)
    base = f"/admin/ui/services/{service.id}"
    try:
        if member_id:
            result = register.check_in_member(db, service, uuid.UUID(member_id), method="manual")
        elif visitor_name.strip():
            result = register.check_in_visitor(
                db, service, visitor_name, visitor_phone, method="manual"
            )
        else:
            return _redirect(f"{base}?msg=pick")
    except (ValueError, register.NotFound):
        return _redirect(f"{base}?msg=cannot")
    msg = "already" if result.already else "added"
    return _redirect(f"{base}?msg={msg}")


@router.post("/services/{service_id}/attendance/{attendance_id}/delete")
def remove_attendance(
    service_id: uuid.UUID,
    attendance_id: uuid.UUID,
    assembly: Assembly = Depends(require_admin_page),
    db: Session = Depends(get_db),
):
    """Undo a wrong tap."""
    service = _service(db, assembly, service_id)
    row = db.scalar(
        select(Attendance).where(
            Attendance.id == attendance_id, Attendance.service_id == service.id
        )
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return _redirect(f"/admin/ui/services/{service.id}?msg=removed")


@router.post("/retention")
def retention(assembly: Assembly = Depends(require_admin_page), db: Session = Depends(get_db)):
    deleted = register.run_retention(db, assembly)
    return _redirect(f"/admin/ui?msg=retention:{deleted}")


# --- members -----------------------------------------------------------------


@router.get("/members", response_class=HTMLResponse)
def members(
    request: Request,
    assembly: Assembly = Depends(require_admin_page),
    db: Session = Depends(get_db),
):
    return _page(
        request,
        "members.html",
        assembly,
        members=register.list_members(db, assembly),
        message=request.query_params.get("msg"),
    )


@router.post("/members")
def add_member(
    first_name: str = Form(...),
    last_name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    notes: str = Form(""),
    consent: bool = Form(False),
    assembly: Assembly = Depends(require_admin_page),
    db: Session = Depends(get_db),
):
    if not first_name.strip() or not last_name.strip():
        return _redirect("/admin/ui/members?msg=names")
    register.create_member(db, assembly, first_name, last_name, phone, email, notes, consent)
    return _redirect("/admin/ui/members?msg=added")


def _member(db: Session, assembly: Assembly, member_id: uuid.UUID):
    member = register.member_for_assembly(db, assembly.id, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@router.post("/members/{member_id}/active")
def toggle_active(
    member_id: uuid.UUID,
    assembly: Assembly = Depends(require_admin_page),
    db: Session = Depends(get_db),
):
    member = _member(db, assembly, member_id)
    member.is_active = not member.is_active
    db.commit()
    return _redirect(f"/admin/ui/members#m-{member.id}")


@router.post("/members/{member_id}/consent")
def toggle_consent(
    member_id: uuid.UUID,
    assembly: Assembly = Depends(require_admin_page),
    db: Session = Depends(get_db),
):
    member = _member(db, assembly, member_id)
    member.consent_at = None if member.consent_at else register.utcnow()
    db.commit()
    return _redirect(f"/admin/ui/members#m-{member.id}")


@router.post("/members/{member_id}/delete")
def delete_member(
    member_id: uuid.UUID,
    assembly: Assembly = Depends(require_admin_page),
    db: Session = Depends(get_db),
):
    register.erase_member(db, _member(db, assembly, member_id))
    return _redirect("/admin/ui/members?msg=deleted")
