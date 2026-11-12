from types import SimpleNamespace

import pytest
import yaml

import output


@pytest.fixture(autouse=True)
def reset_quiet():
    yield
    output.set_quiet(False)


def test_quiet_hides_details_but_keeps_counts(capsys):
    output.set_quiet(True)
    output.detail("2026-11-10 upd [Fall 2026] Acme | SWE Intern | Rejected")
    output.info("12 new emails · 2 added · 5 updated · 1 ghosted")
    out = capsys.readouterr().out
    assert "Acme" not in out and "12 new emails" in out


def test_in_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert not output.in_ci()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert output.in_ci()


def test_safe_error_has_no_ids_or_urls():
    from googleapiclient.errors import HttpError
    err = HttpError(SimpleNamespace(status=429, reason="Too Many Requests"),
                    b'{"error": {"message": "quota"}}',
                    uri="https://gmail.googleapis.com/gmail/v1/users/me/messages/1a122231ed7407d5")
    msg = output.safe_error(err)
    assert msg == "Gmail API error 429 (rate limited)"
    assert "1a122231" not in msg and "http" not in msg
    assert output.safe_error(ValueError("secret subject line")) == "ValueError error"


def test_ci_never_opens_a_browser(monkeypatch, tmp_path):
    import google_auth
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(google_auth, "TOKEN_PATH", tmp_path / "token.json")
    monkeypatch.setattr(google_auth.InstalledAppFlow, "from_client_secrets_file",
                        lambda *a, **k: pytest.fail("tried to open a browser"))
    with pytest.raises(SystemExit, match="gh secret set GOOGLE_TOKEN"):
        google_auth.get_credentials()


def test_workflow_is_safe():
    from pathlib import Path
    wf = yaml.safe_load((Path(__file__).parent.parent / ".github/workflows/track.yml").read_text())
    triggers = wf[True]  # PyYAML reads the "on" key as True
    assert set(triggers) == {"schedule", "workflow_dispatch"}  # never pull requests from forks
    assert wf["permissions"] == {"contents": "read"}
    text = (Path(__file__).parent.parent / ".github/workflows/track.yml").read_text()
    assert "github.event" not in text
