"""The exercise video library file and its checks."""
import json

from app.video_library import DEFAULT_PATH, coverage, validate_entries

GOOD = {"youtube_id": "aBcDeFgHiJk", "title": "Push-up", "channel": "Ch", "category": "push",
        "level": "beginner", "equipment": "none", "duration_sec": 90}


def test_valid_entry_passes():
    assert validate_entries([GOOD]) == []


def test_bad_labels_and_ids():
    bad = [
        {**GOOD, "youtube_id": "aaaaaaaaaa1", "category": "arms"},
        {**GOOD, "youtube_id": "aaaaaaaaaa2", "level": "pro"},
        {**GOOD, "youtube_id": "aaaaaaaaaa3", "equipment": "bands"},
        {**GOOD, "youtube_id": "short"},
        {**GOOD, "youtube_id": "aaaaaaaaaa4", "duration_sec": 0},
        {**GOOD, "youtube_id": "aaaaaaaaaa5", "title": ""},
        {k: v for k, v in GOOD.items() if k != "channel"} | {"youtube_id": "aaaaaaaaaa6"},
    ]
    errors = validate_entries(bad)
    assert len(errors) == 7
    for entry, err in zip(bad, errors):
        assert entry["youtube_id"] in err


def test_duplicate_ids():
    errors = validate_entries([GOOD, GOOD])
    assert len(errors) == 1 and "aBcDeFgHiJk" in errors[0] and "duplicate" in errors[0]


def test_repo_library_file_is_valid():
    assert validate_entries(json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))) == []


def test_coverage_is_cumulative():
    gym = {**GOOD, "youtube_id": "gggggggggg1", "equipment": "gym"}
    cov = coverage([GOOD, gym])
    assert cov[("push", "beginner", "none")] == 1
    assert cov[("push", "advanced", "gym")] == 2
    assert cov[("push", "beginner", "gym")] == 2
    assert cov[("pull", "advanced", "gym")] == 0


def test_coverage_ignores_inactive():
    assert coverage([{**GOOD, "active": False}])[("push", "beginner", "none")] == 0


def _client(status=None, exc=None):
    import httpx

    def handler(request):
        assert request.url.host == "www.youtube.com" and request.url.path == "/oembed"
        assert request.url.params["url"] == "https://www.youtube.com/watch?v=aBcDeFgHiJk"
        if exc:
            raise exc
        return httpx.Response(status, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_is_live():
    import httpx
    import pytest

    from app.video_library import LinkCheckFailed, is_live
    assert is_live("aBcDeFgHiJk", _client(200)) is True
    for status in (401, 403, 404):
        assert is_live("aBcDeFgHiJk", _client(status)) is False
    # A flaky network or a YouTube outage must not mark videos dead.
    with pytest.raises(LinkCheckFailed):
        is_live("aBcDeFgHiJk", _client(exc=httpx.ConnectError("down")))
    with pytest.raises(LinkCheckFailed):
        is_live("aBcDeFgHiJk", _client(500))


def test_upsert_rows_keep_hidden_videos_hidden():
    from app.video_library import upsert_rows
    rows = upsert_rows([GOOD, {**GOOD, "youtube_id": "hhhhhhhhhh1", "active": False}])
    assert [r["active"] for r in rows] == [True, False]
    assert rows[0] == {**GOOD, "active": True}


def test_active_must_be_true_or_false():
    errors = validate_entries([{**GOOD, "active": "no"}])
    assert len(errors) == 1 and "active" in errors[0]
