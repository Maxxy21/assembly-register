"""Admin JSON API. The assembly is the one the admin token belongs to."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import register
from app.auth import require_admin
from app.config import settings
from app.csv_export import absentees_csv
from app.db import get_db
from app.models import Assembly, Attendance, Member, Service
from app.qr import qr_png

router = APIRouter(prefix="/admin")


class ServiceIn(BaseModel):
    service_date: date
    title: str | None = None
    # Naive datetimes are read as the assembly's local time.
    opens_at: datetime | None = None
    closes_at: datetime | None = None


class MemberIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    notes: str | None = None
    consent: bool = False


def _service_out(service: Service, members: int | None = None, visitors: int | None = None) -> dict:
    out = {
        "id": str(service.id),
        "service_date": service.service_date.isoformat(),
        "title": service.title,
        "opens_at": service.opens_at.isoformat(),
        "closes_at": service.closes_at.isoformat(),
        "check_in_url": register.check_in_url(service),
    }
    if members is not None:
        out["members_present"] = members
        out["visitors_present"] = visitors
    return out


def _member_out(m: Member) -> dict:
    return {
        "id": str(m.id),
        "first_name": m.first_name,
        "last_name": m.last_name,
        "phone": m.phone,
        "email": m.email,
        "consent_at": m.consent_at.isoformat() if m.consent_at else None,
        "is_active": m.is_active,
        "notes": m.notes,
        "created_at": m.created_at.isoformat(),
    }


def _attendance_out(a: Attendance) -> dict:
    return {
        "id": str(a.id),
        "member_id": str(a.member_id) if a.member_id else None,
        "name": a.member.full_name if a.member else a.visitor_name,
        "visitor": a.member_id is None,
        "visitor_phone": a.visitor_phone,
        "method": a.method,
        "checked_in_at": a.checked_in_at.isoformat(),
    }


def get_service(
    service_id: uuid.UUID,
    assembly: Assembly = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Service:
    service = register.service_for_assembly(db, assembly, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


@router.post("/services", status_code=201)
def create_service(
    body: ServiceIn,
    assembly: Assembly = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        service = register.create_service(
            db, assembly, body.service_date, body.title, body.opens_at, body.closes_at
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**_service_out(service), "qr_token": service.qr_token}


@router.get("/services")
def list_services(assembly: Assembly = Depends(require_admin), db: Session = Depends(get_db)):
    return [_service_out(s, m, v) for s, m, v in register.list_services(db, assembly)]


@router.get("/services/{service_id}/attendance")
def service_attendance(service: Service = Depends(get_service), db: Session = Depends(get_db)):
    return {
        "service": _service_out(service),
        "attendance": [_attendance_out(a) for a in register.attendance_for(db, service)],
    }


@router.get("/services/{service_id}/absentees")
def service_absentees(service: Service = Depends(get_service), db: Session = Depends(get_db)):
    return {
        "service": _service_out(service),
        "absentees": [
            {"id": str(m.id), "name": m.full_name, "phone": m.phone, "notes": m.notes}
            for m in register.absentees_for(db, service)
        ],
    }


@router.get("/services/{service_id}/absentees.csv")
def service_absentees_csv(service: Service = Depends(get_service), db: Session = Depends(get_db)):
    body = absentees_csv(register.absentees_for(db, service))
    filename = f"absentees-{service.service_date.isoformat()}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/services/{service_id}/qr.png")
def service_qr_png(service: Service = Depends(get_service)):
    caption = [service.assembly.name, f"{service.title} · {service.service_date:%d.%m.%Y}"]
    return Response(
        content=qr_png(register.check_in_url(service), caption),
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="check-in-{service.service_date}.png"'
        },
    )


@router.post("/members", status_code=201)
def create_member(
    body: MemberIn,
    assembly: Assembly = Depends(require_admin),
    db: Session = Depends(get_db),
):
    member = register.create_member(db, assembly, **body.model_dump())
    return _member_out(member)


@router.get("/members")
def list_members(assembly: Assembly = Depends(require_admin), db: Session = Depends(get_db)):
    return [_member_out(m) for m in register.list_members(db, assembly)]


@router.delete("/members/{member_id}", status_code=204)
def delete_member(
    member_id: uuid.UUID,
    assembly: Assembly = Depends(require_admin),
    db: Session = Depends(get_db),
):
    member = register.member_for_assembly(db, assembly.id, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    register.erase_member(db, member)
    return Response(status_code=204)


@router.post("/retention/run")
def run_retention(assembly: Assembly = Depends(require_admin), db: Session = Depends(get_db)):
    deleted = register.run_retention(db, assembly)
    return {"deleted": deleted, "retention_days": settings.retention_days}
