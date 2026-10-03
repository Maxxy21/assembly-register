"""Load the membership roll from a CSV and mark each person as consenting.

    python scripts/seed_members.py roll.csv --assembly hamburg
    python scripts/seed_members.py roll.csv --assembly hamburg --consent-date 2026-09-20

The CSV needs a header row: first_name,last_name,phone,email (phone and
email may be blank). Only load people whose consent you actually hold, for
example on signed forms; --consent-date records when it was given.
Re-running is safe: a row matching an existing member's first name, last
name and phone is skipped.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Assembly, Member

REQUIRED = {"first_name", "last_name", "phone", "email"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path")
    parser.add_argument("--assembly", required=True, help="assembly slug")
    parser.add_argument("--consent-date", help="YYYY-MM-DD the consent was given (default: now)")
    args = parser.parse_args()

    with SessionLocal() as db:
        assembly = db.scalar(select(Assembly).where(Assembly.slug == args.assembly))
        if assembly is None:
            print(f"No assembly with slug {args.assembly!r}", file=sys.stderr)
            return 1

        if args.consent_date:
            day = datetime.fromisoformat(args.consent_date)
            consent_at = day.replace(tzinfo=ZoneInfo(assembly.timezone))
        else:
            consent_at = datetime.now(timezone.utc)

        added = skipped = 0
        with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = REQUIRED - set(reader.fieldnames or [])
            if missing:
                print(f"CSV is missing columns: {', '.join(sorted(missing))}", file=sys.stderr)
                return 1
            for line, row in enumerate(reader, start=2):
                first = (row["first_name"] or "").strip()
                last = (row["last_name"] or "").strip()
                phone = (row["phone"] or "").strip() or None
                email = (row["email"] or "").strip() or None
                if not first or not last:
                    print(f"line {line}: skipped, first and last name are required")
                    skipped += 1
                    continue
                duplicate = db.scalar(
                    select(Member.id).where(
                        Member.assembly_id == assembly.id,
                        func.lower(Member.first_name) == first.lower(),
                        func.lower(Member.last_name) == last.lower(),
                        func.coalesce(Member.phone, "") == (phone or ""),
                    )
                )
                if duplicate:
                    skipped += 1
                    continue
                db.add(
                    Member(
                        assembly_id=assembly.id,
                        first_name=first,
                        last_name=last,
                        phone=phone,
                        email=email,
                        consent_at=consent_at,
                        is_active=True,
                    )
                )
                added += 1
        db.commit()
    print(f"Added {added} member(s) to {assembly.name}; skipped {skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
