import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app import register
from app.models import Attendance, Member, Service
from tests.conftest import TOKEN_A, admin, make_member, make_service

ADMIN_ENDPOINTS = [
    ("post", "/admin/services"),
    ("get", "/admin/services"),
    ("get", "/admin/services/00000000-0000-0000-0000-000000000000/attendance"),
    ("get", "/admin/services/00000000-0000-0000-0000-000000000000/absentees"),
    ("get", "/admin/services/00000000-0000-0000-0000-000000000000/absentees.csv"),
    ("get", "/admin/services/00000000-0000-0000-0000-000000000000/qr.png"),
    ("post", "/admin/members"),
    ("get", "/admin/members"),
    ("delete", "/admin/members/00000000-0000-0000-0000-000000000000"),
    ("post", "/admin/retention/run"),
]


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_endpoints_401_without_token(client, assembly_a, method, path):
    assert client.request(method, path).status_code == 401
    assert client.request(method, path, headers=admin("wrong")).status_code == 401


def test_admin_ui_redirects_to_login(client, assembly_a):
    r = client.get("/admin/ui", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/ui/login"


def test_create_service(client, db, assembly_a):
    r = client.post(
        "/admin/services",
        json={"service_date": "2026-10-04", "opens_at": "2026-10-04T09:00", "closes_at": "2026-10-04T14:00"},
        headers=admin(),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["check_in_url"] == f"https://register.example/s/{body['qr_token']}"
    # Naive times are Europe/Berlin (CEST, UTC+2, in October before the switch).
    opens = datetime.fromisoformat(body["opens_at"])
    assert opens == datetime(2026, 10, 4, 7, 0, tzinfo=timezone.utc)
    service = db.get(Service, body["id"])
    assert service.assembly_id == assembly_a.id

    bad = client.post(
        "/admin/services",
        json={"service_date": "2026-10-04", "opens_at": "2026-10-04T14:00", "closes_at": "2026-10-04T09:00"},
        headers=admin(),
    )
    assert bad.status_code == 422


def test_each_service_gets_a_fresh_token(client, assembly_a):
    tokens = {
        client.post("/admin/services", json={"service_date": "2026-10-04"}, headers=admin()).json()["qr_token"]
        for _ in range(3)
    }
    assert len(tokens) == 3


def test_absentees_excludes_anyone_who_checked_in(client, db, open_service, assembly_a):
    kwame = make_member(db, assembly_a, "Kwame", "Mensah", phone="+49 151 1")
    make_member(db, assembly_a, "Abena", "Osei", phone="+49 151 2")
    client.post(f"/s/{open_service.qr_token}/check-in", data={"member_id": str(kwame.id)})

    r = client.get(f"/admin/services/{open_service.id}/absentees", headers=admin())
    assert [a["name"] for a in r.json()["absentees"]] == ["Abena Osei"]


def test_absentees_excludes_members_without_consent(client, db, open_service, assembly_a):
    make_member(db, assembly_a, "Abena", "Osei")
    make_member(db, assembly_a, "Yaw", "Darko", consent=False)
    make_member(db, assembly_a, "Akua", "Gone", active=False)

    r = client.get(f"/admin/services/{open_service.id}/absentees", headers=admin())
    assert [a["name"] for a in r.json()["absentees"]] == ["Abena Osei"]


def test_absentees_csv(client, db, open_service, assembly_a):
    make_member(db, assembly_a, "Abena", "Osei", phone="+49 151 2345678")
    make_member(db, assembly_a, "=HYPERLINK(1)", "x", phone=None)

    r = client.get(f"/admin/services/{open_service.id}/absentees.csv", headers=admin())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0] == ["name", "phone", "called", "notes"]
    assert ["Abena Osei", "+49 151 2345678", "", ""] in rows
    assert ["'=HYPERLINK(1) x", "", "", ""] in rows


def test_attendance_lists_members_and_visitors(client, db, open_service, assembly_a):
    kwame = make_member(db, assembly_a, "Kwame", "Mensah")
    url = f"/s/{open_service.qr_token}/check-in"
    client.post(url, data={"member_id": str(kwame.id)})
    client.post(url, data={"visitor_name": "Esi Boateng"})
    rows = client.get(f"/admin/services/{open_service.id}/attendance", headers=admin()).json()["attendance"]
    assert {(r["name"], r["visitor"]) for r in rows} == {("Kwame Mensah", False), ("Esi Boateng", True)}

    listed = client.get("/admin/services", headers=admin()).json()
    assert (listed[0]["members_present"], listed[0]["visitors_present"]) == (1, 1)


def test_create_and_list_members(client, assembly_a):
    r = client.post(
        "/admin/members",
        json={"first_name": "Kofi", "last_name": "Adu", "phone": "+49 40 123", "consent": True},
        headers=admin(),
    )
    assert r.status_code == 201
    assert r.json()["consent_at"] is not None
    no_consent = client.post("/admin/members", json={"first_name": "A", "last_name": "B"}, headers=admin())
    assert no_consent.json()["consent_at"] is None
    assert len(client.get("/admin/members", headers=admin()).json()) == 2


def test_delete_member_erases_attendance(client, db, open_service, assembly_a):
    kwame_id = make_member(db, assembly_a, "Kwame", "Mensah").id
    client.post(f"/s/{open_service.qr_token}/check-in", data={"member_id": str(kwame_id)})

    assert client.delete(f"/admin/members/{kwame_id}", headers=admin()).status_code == 204
    db.expunge_all()
    assert db.get(Member, kwame_id) is None
    assert db.scalar(select(func.count()).select_from(Attendance)) == 0
    assert client.delete(f"/admin/members/{kwame_id}", headers=admin()).status_code == 404


def test_retention_deletes_only_old_attendance(client, db, assembly_a):
    old = make_service(db, assembly_a, timedelta(days=-800), timedelta(days=-800, hours=3))
    recent = make_service(db, assembly_a)
    kwame = make_member(db, assembly_a, "Kwame", "Mensah")
    for service in (old, recent):
        register.check_in_member(db, service, kwame.id)
    db.execute(
        Attendance.__table__.update()
        .where(Attendance.service_id == old.id)
        .values(checked_in_at=old.opens_at)
    )
    db.commit()

    r = client.post("/admin/retention/run", headers=admin())
    assert r.json() == {"deleted": 1, "retention_days": 730}
    remaining = db.scalars(select(Attendance.service_id)).all()
    assert remaining == [recent.id]


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_admin_ui_login_and_pages(client, db, open_service, assembly_a):
    make_member(db, assembly_a, "Kwame", "Mensah")
    bad = client.post("/admin/ui/login", data={"token": "nope"})
    assert bad.status_code == 401
    r = client.post("/admin/ui/login", data={"token": TOKEN_A}, follow_redirects=False)
    assert r.status_code == 303
    assert "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=strict" in r.headers["set-cookie"].lower()

    assert "Sunday Service" in client.get("/admin/ui").text
    page = client.get(f"/admin/ui/services/{open_service.id}")
    assert page.status_code == 200
    assert "<svg" in page.text
    assert "Kwame Mensah" in page.text  # in the absentee list
    assert "Mensah, Kwame" in client.get("/admin/ui/members").text
    # The cookie also works for the CSV link on that page.
    assert client.get(f"/admin/services/{open_service.id}/absentees.csv").status_code == 200
