"""A fake-looking configured credential is still a secret, and never echoed."""

from types import SimpleNamespace

from scripts import scan_secrets

from gulbot.config import Settings


def test_configured_secret_cannot_be_exempted_by_fake_markers(tmp_path, monkeypatch, capsys):
    token = "987654321:" + "test_marker" * 4
    monkeypatch.setattr(scan_secrets, "get_settings", lambda: Settings(bot_token=token))
    path = tmp_path / "leaked.txt"
    path.write_text(token)
    monkeypatch.setattr(
        scan_secrets.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b"")
    )
    assert scan_secrets.scan([path]) == 1
    output = capsys.readouterr().out
    assert "leaked.txt" in output
    assert token not in output and token.split(":", 1)[1] not in output
