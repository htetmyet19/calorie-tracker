from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
ALLOWED = {"config.py", "cron.py"}


def test_service_key_only_in_config_and_cron():
    offenders = [p.name for p in sorted(APP.rglob("*.py"))
                 if p.name not in ALLOWED and "SUPABASE_SERVICE_ROLE_KEY" in p.read_text(encoding="utf-8")]
    assert offenders == []
    assert (APP / "cron.py").exists()
