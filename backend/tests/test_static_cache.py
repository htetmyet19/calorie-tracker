"""The app's own files are re-checked by the browser, so a deploy never runs next to stale JS."""
from fastapi.testclient import TestClient

from app.main import app


def test_static_files_must_be_revalidated():
    c = TestClient(app)
    for path in ("/", "/app.js", "/advice.js", "/styles.css"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert r.headers.get("cache-control") == "no-cache", path


def test_api_responses_keep_their_own_headers():
    r = TestClient(app).get("/api/health")
    assert r.headers.get("cache-control") != "no-cache"


def test_pages_load_scripts_and_styles_at_versioned_addresses():
    # Copies saved before no-cache existed are reused without asking; a new address escapes them.
    import pathlib
    import re
    pages = sorted(pathlib.Path("static").glob("*.html"))
    assert pages
    for page in pages:
        refs = re.findall(r'(?:src|href)="(/[^"]+\.(?:js|css)[^"]*)"', page.read_text())
        assert refs, page.name
        for ref in refs:
            assert ref.endswith(f"?v={ASSET_VERSION}"), (page.name, ref)


ASSET_VERSION = 2
