from datetime import timedelta

from sqlalchemy import func, select

from app.models import Attendance
from tests.conftest import make_member, make_service

JSON = {"Accept": "application/json"}


def _count(db, service):
    return db.scalar(select(func.count()).where(Attendance.service_id == service.id))


# --- window ------------------------------------------------------------------


def test_check_in_before_window_is_rejected(client, db, assembly_a):
    service = make_service(db, assembly_a, timedelta(hours=1), timedelta(hours=4))
    kwame = make_member(db, assembly_a, "Kwame", "Mensah")

    r = client.post(f"/s/{service.qr_token}/check-in", data={"member_id": str(kwame.id)}, headers=JSON)
    assert r.status_code == 403
    assert _count(db, service) == 0


def test_check_in_after_window_is_rejected(client, db, assembly_a):
    service = make_service(db, assembly_a, timedelta(hours=-5), timedelta(hours=-1))
    kwame = make_member(db, assembly_a, "Kwame", "Mensah")

    r = client.post(f"/s/{service.qr_token}/check-in", data={"member_id": str(kwame.id)})
    assert r.status_code == 403
    assert "has closed" in r.text
    r = client.post(f"/s/{service.qr_token}/check-in", data={"visitor_name": "Sam"}, headers=JSON)
    assert r.status_code == 403
    assert _count(db, service) == 0


def test_search_is_forbidden_outside_window(client, db, assembly_a):
    service = make_service(db, assembly_a, timedelta(hours=-5), timedelta(hours=-1))
    make_member(db, assembly_a, "Kwame", "Mensah")
    assert client.get(f"/s/{service.qr_token}/members", params={"q": "kw"}).status_code == 403


def test_closed_page_is_friendly_not_404(client, db, assembly_a):
    later = make_service(db, assembly_a, timedelta(hours=1), timedelta(hours=4))
    r = client.get(f"/s/{later.qr_token}")
    assert r.status_code == 200
    assert "Check-in opens at" in r.text

    past = make_service(db, assembly_a, timedelta(hours=-5), timedelta(hours=-1))
    r = client.get(f"/s/{past.qr_token}")
    assert r.status_code == 200
    assert "has closed" in r.text


def test_unknown_token(client):
    assert client.get("/s/not-a-real-token").status_code == 404
    assert client.get("/s/not-a-real-token/members", params={"q": "ab"}).status_code == 404


# --- check-in ----------------------------------------------------------------


def test_double_check_in_does_not_duplicate(client, db, open_service, assembly_a):
    kwame = make_member(db, assembly_a, "Kwame", "Mensah")
    url = f"/s/{open_service.qr_token}/check-in"

    first = client.post(url, data={"member_id": str(kwame.id)}, headers=JSON)
    assert first.status_code == 200
    assert first.json() == {"status": "checked_in", "name": "Kwame"}

    again = client.post(url, data={"member_id": str(kwame.id)}, headers=JSON)
    assert again.status_code == 200
    assert again.json()["status"] == "already"

    html = client.post(url, data={"member_id": str(kwame.id)})
    assert html.status_code == 200
    assert "already checked in" in html.text

    assert _count(db, open_service) == 1


def test_html_check_in_without_javascript(client, db, open_service, assembly_a):
    ama = make_member(db, assembly_a, "Ama", "Owusu-Ansah")
    page = client.get(f"/s/{open_service.qr_token}", params={"q": "ansah"})
    assert "Ama Owusu-Ansah" in page.text
    r = client.post(f"/s/{open_service.qr_token}/check-in", data={"member_id": str(ama.id)})
    assert r.status_code == 200
    assert "Akwaaba, Ama!" in r.text


def test_visitor_check_in_and_resubmit(client, db, open_service):
    url = f"/s/{open_service.qr_token}/check-in"
    data = {"visitor_name": "  Esi   Boateng ", "visitor_phone": "+49 151 2345678"}
    assert client.post(url, data=data, headers=JSON).json()["status"] == "checked_in"
    assert client.post(url, data={"visitor_name": "esi boateng"}, headers=JSON).json()["status"] == "already"
    row = db.scalar(select(Attendance).where(Attendance.service_id == open_service.id))
    assert (row.member_id, row.visitor_name, row.visitor_phone, row.method) == (
        None, "Esi Boateng", "+49 151 2345678", "qr",
    )
    assert _count(db, open_service) == 1


def test_check_in_needs_exactly_one_of_member_or_visitor(client, db, open_service, assembly_a):
    kwame = make_member(db, assembly_a, "Kwame", "Mensah")
    url = f"/s/{open_service.qr_token}/check-in"
    assert client.post(url, data={}, headers=JSON).status_code == 400
    both = {"member_id": str(kwame.id), "visitor_name": "x"}
    assert client.post(url, data=both, headers=JSON).status_code == 400
    assert client.post(url, data={"member_id": "nonsense"}, headers=JSON).status_code == 404


def test_member_without_consent_cannot_check_in_by_id(client, db, open_service, assembly_a):
    hidden = make_member(db, assembly_a, "Yaw", "Darko", consent=False)
    r = client.post(f"/s/{open_service.qr_token}/check-in", data={"member_id": str(hidden.id)}, headers=JSON)
    assert r.status_code == 404


# --- search ------------------------------------------------------------------


def test_search_flags_members_already_checked_in(client, db, open_service, assembly_a):
    kwame = make_member(db, assembly_a, "Kwame", "Mensah")
    make_member(db, assembly_a, "Kwabena", "Asante")
    client.post(f"/s/{open_service.qr_token}/check-in", data={"member_id": str(kwame.id)})

    results = client.get(f"/s/{open_service.qr_token}/members", params={"q": "kw"}).json()["results"]
    assert {(r["name"], r["checked_in"]) for r in results} == {
        ("Kwame Mensah", True),
        ("Kwabena Asante", False),
    }


def test_search_rules(client, db, open_service, assembly_a):
    for i in range(12):
        make_member(db, assembly_a, f"Abena{i}", "Osei")
    make_member(db, assembly_a, "Akosua", "Hidden", consent=False)
    make_member(db, assembly_a, "Akua", "Gone", active=False)
    url = f"/s/{open_service.qr_token}/members"

    assert client.get(url, params={"q": "a"}).status_code == 422
    assert len(client.get(url, params={"q": "abena"}).json()["results"]) == 8
    assert client.get(url, params={"q": "akosua"}).json()["results"] == []
    assert client.get(url, params={"q": "akua"}).json()["results"] == []
    # Wildcards in the query are literal.
    assert client.get(url, params={"q": "%%"}).json()["results"] == []
    # Every word must match.
    names = [r["name"] for r in client.get(url, params={"q": "abena1 os"}).json()["results"]]
    assert names == ["Abena1 Osei", "Abena10 Osei", "Abena11 Osei"]
