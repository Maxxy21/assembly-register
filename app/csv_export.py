import csv
import io
import re

from app.models import Member

_PHONE = re.compile(r"^\+?[\d\s()/.-]+$")


def _cell(value: str | None) -> str:
    """Neutralise spreadsheet formulas (CSV injection) without mangling phone
    numbers like "+49 151 ..." that legitimately start with a plus sign."""
    value = value or ""
    if value[:1] in ("=", "+", "-", "@", "\t", "\r") and not _PHONE.match(value):
        return "'" + value
    return value


def absentees_csv(members: list[Member]) -> str:
    buf = io.StringIO()
    # A BOM makes Excel open the file as UTF-8, so names like "Ɔsei" survive.
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow(["name", "phone", "called", "notes"])
    for m in members:
        writer.writerow([_cell(m.full_name), _cell(m.phone), "", ""])
    return buf.getvalue()
