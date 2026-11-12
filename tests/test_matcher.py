import base64
from datetime import date, datetime
from types import SimpleNamespace

from classifier import Classification
from gmail_client import Email, _body_text
from matcher import AppRow, apply_email, find_row, mark_ghosted, next_stage, normalize_company


def email(day: str, thread="t1", subject="s"):
    return Email(id=f"m-{day}-{thread}", thread_id=thread, date=datetime.fromisoformat(day),
                 sender="x", subject=subject, body="")


def cls(company, role, stage, conf=0.9):
    return Classification(is_application_email=True, company=company, role=role, stage=stage, confidence=conf)


def test_normalize_company():
    assert normalize_company("Stripe, Inc.") == normalize_company("stripe")
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
    apply_email(r, cls("Stripe Inc", "Software Engineer Intern", "Applied"), email("2026-08-05"), 0.7)
    assert (r.stage, r.date_applied) == ("Applied", "2026-08-05")

    # Different thread, same company, similar role -> same row
    m = find_row(rows, "Stripe", "Software Engineering Intern", "t2")
    assert m is r
    apply_email(m, cls("Stripe", "", "Interview"), email("2026-09-01", "t2"), 0.7)
    assert r.stage == "Interview" and r.thread_ids == ["t1", "t2"]

    # Different role at same company -> no match
    assert find_row(rows, "Stripe", "Account Executive", "t3") is None
    # Thread match wins even with no company
    assert find_row(rows, "", "", "t2") is r


def test_locked_row_untouched():
    r = AppRow(tab="F", row_num=2, company="Acme", stage="Interview", locked=True)
    apply_email(r, cls("Acme", "", "Rejected"), email("2026-10-01"), 0.7)
    assert r.stage == "Interview" and not r.dirty


def test_low_confidence_flags_review():
    r = AppRow(tab="F", row_num=None)
    apply_email(r, cls("Acme", "PM", "Applied", conf=0.4), email("2026-10-01"), 0.7)
    assert r.needs_review


def test_ghosted():
    old = AppRow(tab="F", row_num=2, company="A", stage="Applied", last_update="2026-08-01")
    fresh = AppRow(tab="F", row_num=3, company="B", stage="Applied", last_update="2026-11-01")
    interview = AppRow(tab="F", row_num=4, company="C", stage="Interview", last_update="2026-08-01")
    out = mark_ghosted([old, fresh, interview], 30, date(2026, 11, 12))
    assert out == [old] and old.stage == "Ghosted"


def test_row_roundtrip():
    r = AppRow(tab="F", row_num=5, company="A", role="R", stage="OA", locked=True, thread_ids=["a", "b"])
    back = AppRow.from_values("F", 5, ["TRUE" if v is True else "FALSE" if v is False else v for v in r.to_values()])
    assert (back.company, back.locked, back.thread_ids) == ("A", True, ["a", "b"])


def test_body_html_fallback():
    data = base64.urlsafe_b64encode(b"<p>Hello&nbsp;there</p><script>x</script>").decode()
    payload = {"mimeType": "multipart/alternative", "parts": [{"mimeType": "text/html", "body": {"data": data}}]}
    assert "Hello" in _body_text(payload) and "x" not in _body_text(payload)
