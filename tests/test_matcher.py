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


def test_link_cell_roundtrip():
    from sheets import link_formula, link_url
    url = "https://mail.google.com/mail/u/0/#all/abc123"
    assert link_url(link_formula(url)) == url
    assert link_url(url) == url          # bare URL from before the short links
    assert link_url("Open") == "" and link_formula("") == ""


def test_style_requests_cover_every_stage():
    from matcher import STAGES
    from sheet_style import STAGE_COLORS, season_tab_requests
    assert set(STAGE_COLORS) == set(STAGES)
    reqs = season_tab_requests(sheet_id=1, row_count=1000, existing_rules=2)
    kinds = [next(iter(r)) for r in reqs]
    assert kinds.count("deleteConditionalFormatRule") == 2
    assert kinds.count("addConditionalFormatRule") == len(STAGES) + 1


def test_message_link_targets_account():
    from gmail_client import message_id_from_link, message_link
    url = message_link("19fbe9757445876f", "someone@school.edu")
    assert url == "https://mail.google.com/mail/?authuser=someone%40school.edu#all/19fbe9757445876f"
    assert message_id_from_link(url) == "19fbe9757445876f"
    assert message_id_from_link("https://mail.google.com/mail/u/0/#all/abc123") == "abc123"


def test_reached_tracks_every_progress_stage():
    r = AppRow(tab="F", row_num=None)
    apply_email(r, cls("Acme", "SWE", "Applied"), email("2026-09-01"))
    apply_email(r, cls("Acme", "SWE", "OA"), email("2026-09-05"))
    apply_email(r, cls("Acme", "SWE", "Rejected"), email("2026-09-20"))
    assert r.stage == "Rejected" and r.reached == ["Applied", "OA"]

    first_email_is_rejection = AppRow(tab="F", row_num=None)
    apply_email(first_email_is_rejection, cls("Initech", "PM", "Rejected"), email("2026-09-01"))
    assert first_email_is_rejection.reached == ["Applied"]


def test_sync_reached_picks_up_manual_stage():
    from matcher import sync_reached
    r = AppRow(tab="F", row_num=2, company="Acme", stage="Interview", reached=["Applied"])
    assert sync_reached([r]) == 1 and r.reached == ["Applied", "Interview"] and r.dirty
    assert sync_reached([r]) == 0


def test_stats_layout():
    from matcher import STAGES
    from sheet_style import KPI_ROW, KPIS, STAGE_ROW, STATS_COLS, stats_values
    grid = stats_values()
    assert all(len(r) == STATS_COLS for r in grid)
    assert grid[KPI_ROW - 2] == KPIS and "Response rate" not in KPIS
    assert [grid[STAGE_ROW - 1 + i][0] for i in range(len(STAGES))] == STAGES
    # Formulas read the season picked in B2, using the Stage (C) and Reached (I) columns
    assert "$B$2" in grid[KPI_ROW - 1][0] and "!I2:I" in grid[KPI_ROW - 1][3]


def test_pipeline_flows_apps_script():
    """Runs the Apps Script's pure flow logic under Node, if Node is installed."""
    import json, shutil, subprocess
    import pytest
    from pathlib import Path
    if not shutil.which("node"):
        pytest.skip("node not installed")
    rows = [
        {"stage": "Applied", "reached": "Applied"},             # no response
        {"stage": "Rejected", "reached": "Applied"},            # rejected right away
        {"stage": "Rejected", "reached": "Applied,OA"},         # rejected after OA
        {"stage": "Interview", "reached": "Applied,OA,Interview"},  # in progress
        {"stage": "Ghosted", "reached": "Applied"},
        {"stage": "Interview", "reached": "Applied"},           # stage set by hand, Reached not synced yet
    ]
    script = Path(__file__).parent.parent / "apps_script" / "Pipeline.gs"
    js = (f"const m=require('module');const p={json.dumps(str(script))};"
          f"const mod=new m(p);mod.paths=[];mod._compile(require('fs').readFileSync(p,'utf8'),p);"
          f"console.log(JSON.stringify(mod.exports.pipelineFlows({json.dumps(rows)})))")
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    edges = {(a, b): n for a, b, n in out["edges"]}
    assert edges == {
        ("Applied", "OA"): 2, ("Applied", "Interview"): 1, ("OA", "Interview"): 1,
        ("Applied", "No response"): 1, ("Applied", "Ghosted"): 1,
        ("Applied", "Rejected"): 1, ("OA", "Rejected"): 1,
    }
    assert out["totals"]["Applied"] == 6 and out["totals"]["Interview"] == 2
