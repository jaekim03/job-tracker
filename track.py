"""Job application tracker: Gmail -> Claude Haiku -> Google Sheets.

  uv run track.py auth
  uv run track.py new-season "Fall 2026" --start 2026-08-01 --end 2026-12-31
  uv run track.py run [--dry-run] [--limit N] [--since YYYY-MM-DD] [--quiet]
  uv run track.py style
"""
import argparse
import sys
from datetime import date, datetime, timedelta

from config import load_config
from output import detail, in_ci, info, is_quiet, safe_error, set_quiet


def _date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def cmd_auth(_args) -> None:
    from google_auth import get_credentials

    get_credentials(force_login=True)
    print("Google login saved to token.json.")


def cmd_new_season(args) -> None:
    from google_auth import get_credentials
    from sheets import Store

    if args.end and args.end < args.start:
        raise SystemExit("--end must be after --start.")
    cfg = load_config()
    store = Store(get_credentials(), cfg.spreadsheet_id)
    store.create_season(args.name, args.start, args.end)
    print(f"Season '{args.name}' created and set active.")


def cmd_style(_args) -> None:
    from google_auth import get_credentials
    from sheets import Store

    cfg = load_config()
    styled = Store(get_credentials(), cfg.spreadsheet_id).apply_style()
    print(f"Styled: {', '.join(styled) or 'no season tabs yet'}.")


def cmd_run(args) -> None:
    from classifier import classify_all
    from gmail_client import account_email, fetch, gmail_service, search
    from google_auth import get_credentials
    from matcher import AppRow, apply_email, find_row, is_reapplication
    from sheets import Store

    cfg = load_config()
    creds = get_credentials()
    store = Store(creds, cfg.spreadsheet_id)
    store.ensure_schema()
    seasons = store.seasons()
    if not seasons:
        raise SystemExit('No seasons yet. Run: uv run track.py new-season "Fall 2026" '
                         "--start 2026-08-01 --end 2026-12-31")
    active = next((s for s in seasons if s.active), seasons[-1])
    today = date.today()

    # Scan from the earliest season that ended < 90 days ago (catches late replies to old seasons).
    recent = [s for s in seasons if s.end is None or s.end >= today - timedelta(days=90)]
    since = args.since or min(s.start for s in (recent or [active]))
    processed = store.processed()

    gmail = gmail_service(creds)
    query = f"{cfg.gmail_query} after:{since:%Y/%m/%d}"
    ids = [i for i in search(gmail, query) if i not in processed]
    ids.reverse()  # Gmail returns newest first; process oldest first
    if args.limit:
        ids = ids[: args.limit]
    detail(f"{len(ids)} new candidate emails since {since}.")
    if not ids:
        _ghost_and_save(store, store.load_rows(seasons), cfg, today, args.dry_run, [], 0, 0)
        return

    account = account_email(gmail)
    emails = []
    for n, mid in enumerate(ids, 1):
        emails.append(fetch(gmail, mid, cfg.max_body_chars, account))
        if n % 50 == 0:
            detail(f"  fetched {n}/{len(ids)}")
    emails.sort(key=lambda e: e.date)

    results = classify_all(emails, cfg.workers, cfg.llm)
    failed = sum(1 for e in emails if results.get(e.id) is None)
    rows = store.load_rows(seasons)
    log: list[tuple[str, date, str]] = []

    for e in emails:
        c = results.get(e.id)
        if c is None:
            continue  # failed; retried next run
        if not c.is_application_email:
            log.append((e.id, e.date.date(), "not application"))
            continue
        row = find_row(rows, c.company, c.role, e.thread_id)
        if row is not None and is_reapplication(row, c.stage, e.date.date()):
            row = None
        if row is None:
            if c.stage == "Other":
                log.append((e.id, e.date.date(), f"other/no match: {c.company}"))
                continue
            season = next((s for s in seasons if s.contains(e.date.date())), active)
            row = AppRow(tab=season.name, row_num=None)
            rows.append(row)
            label = "NEW"
        else:
            label = "upd"
        changes = apply_email(row, c, e)
        summary = f"{c.company or '?'} | {c.role or '-'} | {c.stage}"
        detail(f"{e.date:%Y-%m-%d} {label} [{row.tab}] {summary}" + (f"  ({'; '.join(changes)})" if changes else ""))
        log.append((e.id, e.date.date(), summary))

    _ghost_and_save(store, rows, cfg, today, args.dry_run, log, len(ids), failed)


def _ghost_and_save(store, rows, cfg, today, dry_run, log, n_emails, failed) -> None:
    from matcher import mark_ghosted, sync_reached

    sync_reached(rows)
    ghosted = mark_ghosted(rows, cfg.ghosted_days, today)
    for r in ghosted:
        detail(f"ghosted [{r.tab}] {r.company} | {r.role}")
    dirty = [r for r in rows if r.dirty]
    new = sum(1 for r in dirty if r.row_num is None)
    if failed:
        info(f"{failed} email(s) failed to classify; they'll be retried next run.")
    if not dry_run:
        store.save_rows(rows)
        store.log_processed(log)
    if is_quiet():
        prefix = "Dry run (nothing written): " if dry_run else ""
        info(f"{prefix}{n_emails} new emails · {new} added · {len(dirty) - new} updated · {len(ghosted)} ghosted")
    elif dry_run:
        info(f"\nDry run: would add {new} rows, update {len(dirty) - new}, log {len(log)} emails. Nothing written.")
    else:
        info(f"\nDone: added {new} rows, updated {len(dirty) - new}, logged {len(log)} emails.")


def main() -> None:
    p = argparse.ArgumentParser(description="Gmail -> Google Sheets job application tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth", help="Log in to Google (opens browser)").set_defaults(fn=cmd_auth)

    ns = sub.add_parser("new-season", help="Create a season tab and make it active")
    ns.add_argument("name")
    ns.add_argument("--start", type=_date, required=True)
    ns.add_argument("--end", type=_date)
    ns.set_defaults(fn=cmd_new_season)

    sub.add_parser("style", help="Reapply the sheet's formatting").set_defaults(fn=cmd_style)

    r = sub.add_parser("run", help="Scan Gmail and update the sheet")
    r.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    r.add_argument("--limit", type=int, help="Only process the N oldest new emails")
    r.add_argument("--since", type=_date, help="Override scan start date")
    r.add_argument("--quiet", action="store_true",
                   help="Print counts only, no email details (automatic on GitHub Actions)")
    r.set_defaults(fn=cmd_run)

    args = p.parse_args()
    set_quiet(getattr(args, "quiet", False) or in_ci())
    try:
        args.fn(args)
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:  # noqa: BLE001 - last-resort handler
        if not is_quiet():
            raise
        # Full tracebacks can include message IDs and URLs; keep public logs clean.
        info(f"Error: {safe_error(e)}. Run locally for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
