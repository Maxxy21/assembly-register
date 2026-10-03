"""Initial schema: assemblies, members, services, attendance.

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assemblies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "timezone", sa.String(64), nullable=False, server_default="Europe/Berlin"
        ),
        sa.Column("contact_email", sa.String(320)),
        sa.Column("admin_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assembly_id",
            UUID(as_uuid=True),
            sa.ForeignKey("assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(40)),
        sa.Column("email", sa.String(320)),
        sa.Column("consent_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notes", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_members_assembly_id", "members", ["assembly_id"])

    op.create_table(
        "services",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assembly_id",
            UUID(as_uuid=True),
            sa.ForeignKey("assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("service_date", sa.Date, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("qr_token", sa.String(64), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("closes_at > opens_at", name="ck_services_window"),
    )
    op.create_index("ix_services_assembly_id", "services", ["assembly_id"])
    op.create_index("ix_services_qr_token", "services", ["qr_token"], unique=True)

    op.create_table(
        "attendance",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "service_id",
            UUID(as_uuid=True),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            UUID(as_uuid=True),
            sa.ForeignKey("members.id", ondelete="CASCADE"),
        ),
        sa.Column("visitor_name", sa.String(200)),
        sa.Column("visitor_phone", sa.String(40)),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column(
            "checked_in_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "service_id", "member_id", name="uq_attendance_service_member"
        ),
        sa.CheckConstraint("method IN ('qr', 'manual')", name="ck_attendance_method"),
        sa.CheckConstraint(
            "member_id IS NOT NULL OR visitor_name IS NOT NULL",
            name="ck_attendance_member_or_visitor",
        ),
    )
    op.create_index("ix_attendance_service_id", "attendance", ["service_id"])
    op.create_index("ix_attendance_member_id", "attendance", ["member_id"])
    op.create_index("ix_attendance_checked_in_at", "attendance", ["checked_in_at"])


def downgrade() -> None:
    op.drop_table("attendance")
    op.drop_table("services")
    op.drop_table("members")
    op.drop_table("assemblies")
