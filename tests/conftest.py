"""Test fixtures.

Tests run against a real PostgreSQL database (the code relies on Postgres
behaviour such as ON CONFLICT and NULLs being distinct in unique
constraints). The schema is built with the Alembic migrations, so the
migrations are tested too. Point TEST_DATABASE_URL at a server you can
create databases on; the database itself is created if missing.
"""

from __future__ import annotations

import os
from datetime import timedelta

import psycopg
import pytest
from sqlalchemy.engine import make_url

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/register_test",
)
# Must be set before the app is imported: the engine is created at import
# time. Never fall back to DATABASE_URL, which may be a real database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["BASE_URL"] = "https://register.example"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import register  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Assembly, Member, Service  # noqa: E402
from app.tokens import hash_admin_token, new_qr_token  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_database(url: str) -> None:
    u = make_url(url)
    admin = u.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (u.database,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{u.database}"')


@pytest.fixture(scope="session", autouse=True)
def schema():
    _ensure_database(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE attendance, services, members, assemblies CASCADE"))


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    # https so the Secure admin cookie is sent back, as it would be in production.
    return TestClient(app, base_url="https://testserver")


# --- builders ------------------------------------------------------------------


def make_assembly(db, slug: str, token: str) -> Assembly:
    assembly = Assembly(
        name=f"Assembly {slug}",
        slug=slug,
        contact_email=f"office@{slug}.example",
        admin_token_hash=hash_admin_token(token),
    )
    db.add(assembly)
    db.commit()
    return assembly


def make_member(db, assembly, first, last, phone=None, consent=True, active=True) -> Member:
    member = Member(
        assembly_id=assembly.id,
        first_name=first,
        last_name=last,
        phone=phone,
        consent_at=register.utcnow() if consent else None,
        is_active=active,
    )
    db.add(member)
    db.commit()
    return member


def make_service(db, assembly, opens_delta=timedelta(hours=-1), closes_delta=timedelta(hours=2)) -> Service:
    now = register.utcnow()
    service = Service(
        assembly_id=assembly.id,
        service_date=now.date(),
        title="Sunday Service",
        qr_token=new_qr_token(),
        opens_at=now + opens_delta,
        closes_at=now + closes_delta,
    )
    db.add(service)
    db.commit()
    return service


TOKEN_A = "token-for-assembly-a"
TOKEN_B = "token-for-assembly-b"


@pytest.fixture
def assembly_a(db):
    return make_assembly(db, "a", TOKEN_A)


@pytest.fixture
def assembly_b(db):
    return make_assembly(db, "b", TOKEN_B)


@pytest.fixture
def open_service(db, assembly_a):
    return make_service(db, assembly_a)


def admin(token: str = TOKEN_A) -> dict:
    return {"X-Admin-Token": token}
