"""advice_requests: a per-user daily limit that clients can't reset."""
import pytest

pytestmark = pytest.mark.integration

REP = {"Prefer": "return=representation"}


def test_advice_limit_and_no_tampering(make_user, rest):
    a, b = make_user("client"), make_user("client")
    for _ in range(30):
        assert rest(a.token).post("/advice_requests", json={"user_id": a.id}).status_code == 201
    r = rest(a.token).post("/advice_requests", json={"user_id": a.id})
    assert r.status_code == 400 and r.json()["message"] == "advice_limit"
    # Another user's count is separate, and nobody can insert for someone else.
    assert rest(b.token).post("/advice_requests", json={"user_id": b.id}).status_code == 201
    assert rest(b.token).post("/advice_requests", json={"user_id": a.id}).status_code in (401, 403)
    # The count can't be reset: no delete, no update, no backdated insert.
    r = rest(a.token).delete("/advice_requests", params={"user_id": f"eq.{a.id}"}, headers=REP)
    assert r.status_code in (401, 403) or r.json() == []
    r = rest(a.token).patch("/advice_requests", params={"user_id": f"eq.{a.id}"},
                            json={"created_at": "2000-01-01T00:00:00Z"}, headers=REP)
    assert r.status_code in (401, 403) or r.json() == []
    r = rest(b.token).post("/advice_requests", json={"user_id": b.id, "created_at": "2000-01-01T00:00:00Z"})
    assert r.status_code in (401, 403)
    r = rest(b.token).get("/advice_requests", params={"user_id": f"eq.{a.id}"})
    assert r.status_code == 200 and r.json() == []
