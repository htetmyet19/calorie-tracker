import pytest

pytestmark = pytest.mark.integration


def test_client_reads_only_own_meals(make_user, rest, add_meal):
    a, b = make_user("client"), make_user("client")
    add_meal(a)
    own = rest(a.token).get("/meals", params={"user_id": f"eq.{a.id}"})
    assert own.status_code == 200 and len(own.json()) == 1  # sanity: data is visible to owner
    r = rest(b.token).get("/meals", params={"user_id": f"eq.{a.id}"})
    assert r.status_code == 200
    assert r.json() == []


def test_active_trainer_reads_client_meals(make_user, rest, link, add_meal):
    client, trainer = make_user("client"), make_user("trainer")
    add_meal(client)
    link(client, trainer, "active")
    r = rest(trainer.token).get("/meals", params={"user_id": f"eq.{client.id}"})
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["user_id"] == client.id


@pytest.mark.parametrize("status", ["requested", "declined", "ended"])
def test_inactive_link_hides_meals(make_user, rest, link, add_meal, status):
    client, trainer = make_user("client"), make_user("trainer")
    add_meal(client)
    link(client, trainer, status)
    r = rest(trainer.token).get("/meals", params={"user_id": f"eq.{client.id}"})
    assert r.status_code == 200
    assert r.json() == []


def test_admin_cannot_read_client_meals(make_user, rest, add_meal):
    client, admin = make_user("client"), make_user("admin")  # admin row inserted via service key
    add_meal(client)
    r = rest(admin.token).get("/meals", params={"user_id": f"eq.{client.id}"})
    assert r.status_code == 200
    assert r.json() == []


def test_trainer_cannot_write_client_meals(make_user, rest, link, service):
    client, trainer = make_user("client"), make_user("trainer")
    link(client, trainer, "active")  # even an active trainer may not write
    r = rest(trainer.token).post("/meals", json={
        "user_id": client.id, "eaten_at": "2026-10-31T12:00:00",
        "meal_type": "lunch", "items": [], "total_calories": 1})
    assert r.status_code in (401, 403)
    rows = service.get("/meals", params={"user_id": f"eq.{client.id}"}).json()
    assert rows == []


def test_cannot_self_assign_admin(make_user, rest, service):
    u = make_user(None)
    r = rest(u.token).post("/profiles", json={"id": u.id, "role": "admin"})
    assert r.status_code in (401, 403)
    assert service.get("/profiles", params={"id": f"eq.{u.id}"}).json() == []


def test_cannot_change_role(make_user, rest, service):
    u = make_user("client")
    r = rest(u.token).patch("/profiles", params={"id": f"eq.{u.id}"}, json={"role": "admin"})
    assert r.status_code in (401, 403)
    rows = service.get("/profiles", params={"id": f"eq.{u.id}"}).json()
    assert len(rows) == 1 and rows[0]["role"] == "client"


def test_one_open_link_per_client(make_user, link):
    client, t1, t2 = make_user("client"), make_user("trainer"), make_user("trainer")
    link(client, t1, "requested")
    with pytest.raises(AssertionError, match="409"):
        link(client, t2, "requested")
