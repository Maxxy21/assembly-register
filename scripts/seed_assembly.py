"""Create an assembly (church) and its admin token, or rotate the token.

    python scripts/seed_assembly.py                       # first assembly, from .env
    python scripts/seed_assembly.py --name "..." --slug hamburg-north
    python scripts/seed_assembly.py --slug hamburg --rotate-token

The token is printed once and only its SHA-256 digest is stored. If
ADMIN_TOKEN is set in the environment it is used for the new assembly
(handy for the very first one); otherwise a random token is generated.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Assembly
from app.tokens import hash_admin_token, new_admin_token


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "assembly"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default=os.environ.get("CHURCH_NAME"))
    parser.add_argument("--slug")
    parser.add_argument("--timezone", default="Europe/Berlin")
    parser.add_argument("--contact-email")
    parser.add_argument("--rotate-token", action="store_true", help="issue a new token for --slug")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.rotate_token:
            if not args.slug:
                parser.error("--rotate-token needs --slug")
            assembly = db.scalar(select(Assembly).where(Assembly.slug == args.slug))
            if assembly is None:
                print(f"No assembly with slug {args.slug!r}", file=sys.stderr)
                return 1
            token = new_admin_token()
            assembly.admin_token_hash = hash_admin_token(token)
            db.commit()
            print(f"New admin token for {assembly.name}:\n\n    {token}\n")
            print("The old token stops working now. Store this one in your password manager.")
            return 0

        if not args.name:
            parser.error("--name is required (or set CHURCH_NAME)")
        slug = args.slug or slugify(args.name)
        if db.scalar(select(Assembly).where(Assembly.slug == slug)):
            print(f"Assembly {slug!r} already exists. Use --rotate-token to issue a new token.")
            return 0

        env_token = os.environ.get("ADMIN_TOKEN", "").strip()
        if env_token and len(env_token) < 24:
            print("ADMIN_TOKEN is too short (need 24+ characters).", file=sys.stderr)
            return 1
        token = env_token or new_admin_token()
        assembly = Assembly(
            name=args.name,
            slug=slug,
            timezone=args.timezone,
            contact_email=args.contact_email,
            admin_token_hash=hash_admin_token(token),
        )
        db.add(assembly)
        db.commit()
        print(f"Created assembly {assembly.name!r} (slug {slug}).")
        if env_token:
            print("Its admin token is the ADMIN_TOKEN from your environment.")
            print("You can now remove ADMIN_TOKEN from .env; the app never reads it.")
        else:
            print(f"Admin token (shown once):\n\n    {token}\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
