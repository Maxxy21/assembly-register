"""Attendance logic shared by the public check-in pages and the admin side.

Every function takes the assembly (or a service, which carries its assembly)
and scopes its queries by it. Nothing here trusts an id from the outside
without checking that it belongs to the same assembly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Assembly, Attendance, Member, Service
from app.tokens import new_qr_token

SEARCH_MIN_CHARS = 2
SEARCH_MAX_RESULTS = 8


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def check_in_url(service: Service) -> str:
    return f"{settings.base_url}/s/{service.qr_token}"


# --- services ----------------------------------------------------------------


def next_sunday(tz: str, today: date | None = None) -> date:
    today = today or datetime.now(ZoneInfo(tz)).date()
    return today + timedelta(days=(6 - today.weekday()) % 7)


def _localize(value: datetime | time, on: date, tz: str) -> datetime:
    zone = ZoneInfo(tz)
    if isinstance(value, time):
        return datetime.combine(on, value, tzinfo=zone)
    return value if value.tzinfo else value.replace(tzinfo=zone)


def create_service(
    db: Session,
    assembly: Assembly,
    service_date: date,
    title: str | None = None,
    opens: datetime | time | None = None,
    closes: datetime | time | None = None,
) -> Service:
    opens_at = _localize(opens or settings.default_opens, service_date, assembly.timezone)
    closes_at = _localize(closes or settings.default_closes, service_date, assembly.timezone)
    if closes_at <= opens_at:
        raise ValueError("The check-in window must close after it opens.")
    service = Service(
        assembly_id=assembly.id,
        service_date=service_date,
        title=(title or "").strip() or "Sunday Service",
        qr_token=new_qr_token(),
        opens_at=opens_at,
        closes_at=closes_at,
    )
    db.add(service)
    db.commit()
    return service


def service_by_token(db: Session, token: str) -> Service | None:
    return db.scalar(select(Service).where(Service.qr_token == token))


def service_for_assembly(db: Session, assembly: Assembly, service_id: uuid.UUID) -> Service | None:
    return db.scalar(
        select(Service).where(Service.id == service_id, Service.assembly_id == assembly.id)
    )


def list_services(db: Session, assembly: Assembly) -> list[tuple[Service, int, int]]:
    """Services newest first, with (member count, visitor count)."""
    members = func.count(Attendance.member_id)
    visitors = func.count(Attendance.id).filter(Attendance.member_id.is_(None))
    rows = db.execute(
        select(Service, members, visitors)
        .outerjoin(Attendance, Attendance.service_id == Service.id)
        .where(Service.assembly_id == assembly.id)
        .group_by(Service.id)
        .order_by(Service.service_date.desc(), Service.opens_at.desc())
    ).all()
    return [(s, m, v) for s, m, v in rows]


# --- members -----------------------------------------------------------------


def _searchable(assembly_id: uuid.UUID):
    """Members who may appear in a search or an absentee list."""
    return and_(
        Member.assembly_id == assembly_id,
        Member.is_active.is_(True),
        Member.consent_at.is_not(None),
    )


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class SearchHit:
    id: uuid.UUID
    name: str
    checked_in: bool


def search_members(db: Session, service: Service, q: str) -> list[SearchHit]:
    """Every typed word must match the start of some part of the name, so
    "kwa men" finds Kwame Mensah and "ansah" finds Ama Owusu-Ansah."""
    terms = q.lower().split()[:4]
    if not terms:
        return []
    full = func.lower(Member.first_name + " " + Member.last_name)
    conditions = []
    for term in terms:
        t = _escape_like(term)
        conditions.append(
            or_(
                full.like(f"{t}%", escape="\\"),
                full.like(f"% {t}%", escape="\\"),
                full.like(f"%-{t}%", escape="\\"),
            )
        )
    present = (
        select(Attendance.id)
        .where(Attendance.service_id == service.id, Attendance.member_id == Member.id)
        .exists()
    )
    rows = db.execute(
        select(Member, present)
        .where(_searchable(service.assembly_id), *conditions)
        .order_by(Member.first_name, Member.last_name)
        .limit(SEARCH_MAX_RESULTS)
    ).all()
    return [SearchHit(m.id, m.full_name, bool(p)) for m, p in rows]


def member_for_assembly(db: Session, assembly_id: uuid.UUID, member_id: uuid.UUID) -> Member | None:
    return db.scalar(
        select(Member).where(Member.id == member_id, Member.assembly_id == assembly_id)
    )


def list_members(db: Session, assembly: Assembly) -> list[Member]:
    return list(
        db.scalars(
            select(Member)
            .where(Member.assembly_id == assembly.id)
            .order_by(Member.last_name, Member.first_name)
        )
    )


def create_member(
    db: Session,
    assembly: Assembly,
    first_name: str,
    last_name: str,
    phone: str | None = None,
    email: str | None = None,
    notes: str | None = None,
    consent: bool = False,
) -> Member:
    member = Member(
        assembly_id=assembly.id,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        phone=(phone or "").strip() or None,
        email=(email or "").strip() or None,
        notes=(notes or "").strip() or None,
        consent_at=utcnow() if consent else None,
        is_active=True,
    )
    db.add(member)
    db.commit()
    return member


def erase_member(db: Session, member: Member) -> None:
    """Full erasure. Attendance rows go with the member via ON DELETE CASCADE."""
    db.delete(member)
    db.commit()


# --- check-in ----------------------------------------------------------------


@dataclass
class CheckInResult:
    name: str
    already: bool


class NotFound(Exception):
    pass


def check_in_member(
    db: Session, service: Service, member_id: uuid.UUID, method: str = "qr"
) -> CheckInResult:
    member = db.scalar(
        select(Member).where(Member.id == member_id, _searchable(service.assembly_id))
    )
    if member is None:
        raise NotFound
    inserted = db.scalar(
        pg_insert(Attendance)
        .values(id=uuid.uuid4(), service_id=service.id, member_id=member.id, method=method)
        .on_conflict_do_nothing(constraint="uq_attendance_service_member")
        .returning(Attendance.id)
    )
    db.commit()
    return CheckInResult(member.first_name, already=inserted is None)


def check_in_visitor(
    db: Session, service: Service, name: str, phone: str | None, method: str = "qr"
) -> CheckInResult:
    name = " ".join(name.split())[:200]
    phone = (phone or "").strip()[:40] or None
    if not name:
        raise ValueError("Please enter your name.")
    # A visitor who submits twice (or taps again after a slow response) should
    # see "already checked in", not create a second row.
    existing = db.scalar(
        select(Attendance.id).where(
            Attendance.service_id == service.id,
            Attendance.member_id.is_(None),
            func.lower(Attendance.visitor_name) == name.lower(),
        )
    )
    if existing is None:
        db.add(
            Attendance(
                service_id=service.id,
                visitor_name=name,
                visitor_phone=phone,
                method=method,
            )
        )
        db.commit()
    return CheckInResult(name.split()[0], already=existing is not None)


# --- reports -----------------------------------------------------------------


def attendance_for(db: Session, service: Service) -> list[Attendance]:
    return list(
        db.scalars(
            select(Attendance)
            .where(Attendance.service_id == service.id)
            .order_by(Attendance.checked_in_at)
        )
    )


def absentees_for(db: Session, service: Service) -> list[Member]:
    """Active, consented members of the service's assembly with no check-in."""
    checked_in = exists().where(
        Attendance.service_id == service.id, Attendance.member_id == Member.id
    )
    return list(
        db.scalars(
            select(Member)
            .where(_searchable(service.assembly_id), ~checked_in)
            .order_by(Member.last_name, Member.first_name)
        )
    )


def run_retention(db: Session, assembly: Assembly, days: int | None = None) -> int:
    cutoff = utcnow() - timedelta(days=days if days is not None else settings.retention_days)
    in_assembly = select(Service.id).where(Service.assembly_id == assembly.id)
    result = db.execute(
        delete(Attendance).where(
            Attendance.service_id.in_(in_assembly), Attendance.checked_in_at < cutoff
        )
    )
    db.commit()
    return result.rowcount
