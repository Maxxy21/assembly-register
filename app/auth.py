"""Admin authentication.

Each assembly has its own admin token; the token both authenticates the
caller and decides which assembly every admin query is scoped to. API
clients send it in the X-Admin-Token header. The browser UI keeps it in an
HttpOnly, SameSite=Strict cookie after signing in, so the same endpoints
(e.g. the absentee CSV) work from a plain link.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Assembly
from app.tokens import hash_admin_token

COOKIE_NAME = "admin_token"


def assembly_for_token(db: Session, token: str | None) -> Assembly | None:
    if not token:
        return None
    digest = hash_admin_token(token)
    assembly = db.scalar(select(Assembly).where(Assembly.admin_token_hash == digest))
    # The lookup is by digest, so a timing difference there reveals nothing
    # about the token itself; compare_digest is the final, constant-time check.
    if assembly is None or not secrets.compare_digest(assembly.admin_token_hash, digest):
        return None
    return assembly


def require_admin(
    request: Request,
    db: Session = Depends(get_db),
    x_admin_token: str | None = Header(default=None),
) -> Assembly:
    token = x_admin_token or request.cookies.get(COOKIE_NAME)
    assembly = assembly_for_token(db, token)
    if assembly is None:
        raise HTTPException(status_code=401, detail="Missing or invalid admin token")
    return assembly


class LoginRequired(Exception):
    pass


def require_admin_page(request: Request, db: Session = Depends(get_db)) -> Assembly:
    assembly = assembly_for_token(db, request.cookies.get(COOKIE_NAME))
    if assembly is None:
        raise LoginRequired
    return assembly
