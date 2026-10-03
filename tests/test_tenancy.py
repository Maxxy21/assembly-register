"""A token for assembly A must never read or change assembly B's data."""

from sqlalchemy import func, select

from app.models import Attendance, Member
from tests.conftest import TOKEN_A, TOKEN_B, admin, make_member, make_service


def test_admin_token_is_scoped_to_its_assembly(client, db, assembly_a, assembly_b):
    service_b = make_service(db, assembly_b)
    member_b = make_member(db, assembly_b, "Kwame", "Bee")
    make_member(db, assembly_a, "Kwame", "Ay")

    for path in (
        f"/admin/services/{service_b.id}/attendance",
        f"/admin/services/{service_b.id}/absentees",
        f"/admin/services/{service_b.id}/absentees.csv",
        f"/admin/services/{service_b.id}/qr.png",
    ):
        assert client.get(path, headers=admin(TOKEN_A)).status_code == 404, path
        assert client.get(path, headers=admin(TOKEN_B)).status_code == 200, path

    assert client.get("/admin/services", headers=admin(TOKEN_A)).json() == []
    names = [m["last_name"] for m in client.get("/admin/members", headers=admin(TOKEN_A)).json()]
    assert names == ["Ay"]

    assert client.delete(f"/admin/members/{member_b.id}", headers=admin(TOKEN_A)).status_code == 404
    assert db.get(Member, member_b.id) is not None


def test_service_token_is_scoped_to_its_assembly(client, db, assembly_a, assembly_b):
    service_a = make_service(db, assembly_a)
    service_b = make_service(db, assembly_b)
    make_member(db, assembly_a, "Kwame", "Ay")
    member_b = make_member(db, assembly_b, "Kwame", "Bee")

    results = client.get(f"/s/{service_a.qr_token}/members", params={"q": "kwame"}).json()["results"]
    assert [r["name"] for r in results] == ["Kwame Ay"]

    # Checking a B member in through A's code is refused.
    r = client.post(
        f"/s/{service_a.qr_token}/check-in",
        data={"member_id": str(member_b.id)},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 404
    assert db.scalar(select(func.count()).select_from(Attendance)) == 0

    # And B's absentee list is untouched by anything that happened in A.
    absent = client.get(f"/admin/services/{service_b.id}/absentees", headers=admin(TOKEN_B)).json()
    assert [a["name"] for a in absent["absentees"]] == ["Kwame Bee"]


def test_admin_ui_cookie_is_scoped_too(client, db, assembly_a, assembly_b):
    service_b = make_service(db, assembly_b)
    member_b = make_member(db, assembly_b, "Kwame", "Bee")
    client.post("/admin/ui/login", data={"token": TOKEN_A})
    assert client.get(f"/admin/ui/services/{service_b.id}").status_code == 404
    assert client.post(f"/admin/ui/members/{member_b.id}/delete").status_code == 404
    assert db.get(Member, member_b.id) is not None
