import base64
from datetime import date, datetime
from types import SimpleNamespace

from classifier import Classification
from gmail_client import Email, _body_text
from matcher import (HEADERS, AppRow, apply_email, find_row, is_reapplication, mark_ghosted, next_stage,
                     normalize_company)


def email(day: str, thread="t1", subject="s"):
    return Email(id=f"m-{day}-{thread}", thread_id=thread, date=datetime.fromisoformat(day),
                 sender="x", subject=subject, body="")


def cls(company, role, stage):
    return Classification(is_application_email=True, company=company, role=role, stage=stage)


def test_normalize_company():
    assert normalize_company("Initech, Inc.") == normalize_company("initech")
    assert normalize_company("The Walt Disney Company") == "waltdisney"


def test_stage_progression():
    assert next_stage("Applied", "Interview") == "Interview"
    assert next_stage("Interview", "Applied") == "Interview"
    assert next_stage("Interview", "Rejected") == "Rejected"
    assert next_stage("Rejected", "Interview") == "Rejected"
    assert next_stage("Ghosted", "Interview") == "Interview"
    assert next_stage("OA", "Other") == "OA"


def test_full_lifecycle_and_matching():
    rows = []
    r = AppRow(tab="Fall 2026", row_num=None)
    rows.append(r)
    apply_email(r, cls("Initech Inc", "Software Engineer Intern", "Applied"), email("2026-08-05"))
    assert (r.stage, r.date_applied) == ("Applied", "2026-08-05")

    # Different thread, same company, similar role -> same row
    m = find_row(rows, "Initech", "Software Engineering Intern", "t2")
    assert m is r
    apply_email(m, cls("Initech", "", "Interview"), email("2026-09-01", "t2"))
    assert r.stage == "Interview" and r.thread_ids == ["t1", "t2"]

    # Different role at same company -> no match
    assert find_row(rows, "Initech", "Account Executive", "t3") is None
    # Thread match wins even with no company
    assert find_row(rows, "", "", "t2") is r


def test_different_roles_same_company_and_thread_stay_separate():
    rows = []
    r = AppRow(tab="F", row_num=None)
    rows.append(r)
    apply_email(r, cls("Acme", "Internship, Software Integration Engineer, Service Tooling (Fall 2026)", "Rejected"),
                email("2026-08-01", "acme-thread"))
    other = "Internship, Software Engineer, Maps & Navigation Validation (Fall 2026)"
    assert find_row(rows, "Acme", other, "acme-thread") is None
    assert find_row(rows, "Acme", "Software Integration Engineer Intern, Service Tooling", "x") is r


def test_reapplication_after_rejection():
    r = AppRow(tab="F", row_num=2, company="Acme", stage="Rejected", last_update="2026-08-01")
    assert is_reapplication(r, "Applied", date(2026, 10, 9))
    assert not is_reapplication(r, "Applied", date(2026, 8, 5))  # same-day/near confirmation
    assert not is_reapplication(r, "Interview", date(2026, 10, 9))


def test_has_data_needs_company_role_or_stage():
    from sheets import _has_data
    assert not _has_data(["", "", "", "", "", "", "a note", ""])
    assert _has_data(["Acme", "", "", "", "", "", "", ""])


def test_manual_stage_edit_survives_older_stage_email():
    r = AppRow(tab="F", row_num=2, company="Acme", stage="Withdrawn", last_update="2026-09-01")
    apply_email(r, cls("Acme", "", "Interview"), email("2026-10-01"))
    assert r.stage == "Withdrawn"


def test_ghosted():
    old = AppRow(tab="F", row_num=2, company="A", stage="Applied", last_update="2026-08-01")
    fresh = AppRow(tab="F", row_num=3, company="B", stage="Applied", last_update="2026-11-01")
    interview = AppRow(tab="F", row_num=4, company="C", stage="Interview", last_update="2026-08-01")
    out = mark_ghosted([old, fresh, interview], 30, date(2026, 11, 12))
    assert out == [old] and old.stage == "Ghosted"


def test_row_roundtrip():
    r = AppRow(tab="F", row_num=5, company="A", role="R", stage="OA", gmail_link="L", notes="n",
               thread_ids=["a", "b"])
    assert len(r.to_values()) == len(HEADERS)
    back = AppRow.from_values("F", 5, r.to_values())
    assert (back.company, back.gmail_link, back.notes, back.thread_ids) == ("A", "L", "n", ["a", "b"])


def test_body_html_fallback():
    data = base64.urlsafe_b64encode(b"<p>Hello&nbsp;there</p><script>x</script>").decode()
    payload = {"mimeType": "multipart/alternative", "parts": [{"mimeType": "text/html", "body": {"data": data}}]}
    assert "Hello" in _body_text(payload) and "x" not in _body_text(payload)
