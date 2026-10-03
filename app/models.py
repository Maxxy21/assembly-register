"""Data model.

Every member and service belongs to exactly one assembly. Attendance has no
assembly_id of its own: it is reached through its service, and the application
guarantees that a check-in only ever links a member and a service of the same
assembly.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Assembly(Base):
    __tablename__ = "assemblies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Europe/Berlin"
    )
    contact_email: Mapped[str | None] = mapped_column(String(320))
    # SHA-256 hex digest of the assembly's admin token. The token itself is
    # shown once by scripts/seed_assembly.py and never stored.
    admin_token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = _created_at()


class Member(Base):
    __tablename__ = "members"

    id: Mapped[uuid.UUID] = _uuid_pk()
    assembly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assemblies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(320))
    # NULL means no consent: the member is invisible to name search and to
    # absentee lists.
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("closes_at > opens_at", name="ck_services_window"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    assembly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assemblies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    qr_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = _created_at()

    assembly: Mapped[Assembly] = relationship(lazy="joined")

    def is_open(self, now: datetime) -> bool:
        return self.opens_at <= now < self.closes_at


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        # Postgres treats NULLs as distinct, so any number of visitors
        # (member_id NULL) can check in to the same service.
        UniqueConstraint("service_id", "member_id", name="uq_attendance_service_member"),
        CheckConstraint("method IN ('qr', 'manual')", name="ck_attendance_method"),
        CheckConstraint(
            "member_id IS NOT NULL OR visitor_name IS NOT NULL",
            name="ck_attendance_member_or_visitor",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("members.id", ondelete="CASCADE"),
        index=True,
    )
    visitor_name: Mapped[str | None] = mapped_column(String(200))
    visitor_phone: Mapped[str | None] = mapped_column(String(40))
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    checked_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    member: Mapped[Member | None] = relationship()
