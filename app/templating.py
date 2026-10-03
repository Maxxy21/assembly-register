from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from app.config import settings

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["retention_days"] = settings.retention_days


def _local(value: datetime, tz: str) -> datetime:
    return value.astimezone(ZoneInfo(tz))


def fmt_time(value: datetime, tz: str) -> str:
    return _local(value, tz).strftime("%H:%M")


def fmt_datetime(value: datetime, tz: str) -> str:
    return _local(value, tz).strftime("%a %d %b %Y, %H:%M")


def fmt_date(value: date) -> str:
    # e.g. "Sunday 4 October 2026"; no locale dependency, no leading zero.
    return f"{value.strftime('%A')} {value.day} {value.strftime('%B %Y')}"


templates.env.filters["time"] = fmt_time
templates.env.filters["datetime"] = fmt_datetime
templates.env.filters["longdate"] = fmt_date


def fmt_period(days: int) -> str:
    if days % 365 == 0:
        years = days // 365
        return "1 year" if years == 1 else f"{years} years"
    return f"{days} days"


templates.env.filters["period"] = fmt_period
