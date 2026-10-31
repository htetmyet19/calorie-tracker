"""Store's HTTP client handling; no network (httpx MockTransport)."""
import httpx

from app import config, store
from app.auth import User


def test_requests_share_one_client_and_follow_config_url(monkeypatch):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=[])

    monkeypatch.setattr(store, "_http", httpx.Client(transport=httpx.MockTransport(handler)))
    s = store.Store(User(id="u1", token="t"))
    monkeypatch.setattr(config, "SUPABASE_URL", "http://a.example/")
    s.get_profile()
    monkeypatch.setattr(config, "SUPABASE_URL", "http://b.example")
    s.get_profile()
    assert [u.split("?")[0] for u in seen] == [
        "http://a.example/rest/v1/profiles", "http://b.example/rest/v1/profiles"]
    assert store._client() is store._client()
