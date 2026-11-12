# job-tracker

Keeps a Google Sheet of your job applications up to date by reading your Gmail.

Each run finds recruiting emails, asks Claude Haiku what each one means, and updates the sheet: one tab per recruiting season, one row per company and role.

| Company | Role | Stage | Date Applied | Last Update | Gmail Link | Notes |
|---|---|---|---|---|---|---|
| Acme | Software Engineer Intern | Interview | 2026-09-02 | 2026-09-20 | link | |

**Stages:** Applied → OA → Interview → Offer, plus Rejected, Withdrawn and Ghosted (no email for 60 days).

A **Stats** tab shows totals, response, OA and interview rates, and a breakdown by stage. A **Pipeline** menu draws a flow chart of where your applications went.

## Setup

You need [uv](https://docs.astral.sh/uv/), a Google account and an [Anthropic API key](https://platform.claude.com).

1. **Install**
   ```bash
   git clone https://github.com/jaekim03/job-tracker.git
   cd job-tracker
   uv sync
   ```
2. **Google Cloud** ([console.cloud.google.com](https://console.cloud.google.com))
   - Create a project and enable the **Gmail API** and **Google Sheets API**.
   - Set up the OAuth consent screen as **External** and add your email as a **test user**.
   - Create an OAuth client ID of type **Desktop app**, download the JSON and save it as `credentials.json` in this folder.
3. **Anthropic API key**
   ```bash
   echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
   ```
4. **Sheet**: create a blank Google Sheet, then copy the config and paste the sheet's link into `spreadsheet_id`.
   ```bash
   cp config.example.yaml config.yaml
   ```
5. **Log in and create your first season**
   ```bash
   uv run track.py auth
   uv run track.py new-season "Fall 2026" --start 2026-08-01 --end 2026-12-31
   ```

6. **Pipeline chart (optional)**: in the sheet, open **Extensions → Apps Script**, replace the contents of `Code.gs` with [`apps_script/Pipeline.gs`](apps_script/Pipeline.gs), click Save, then reload the sheet. Use **Pipeline → Show pipeline**. Google asks you to authorize the script the first time.

**School or work account?** If it won't let you create a Cloud project, create the project with a personal Google account, add your school address as a test user, and log in with the school account in step 5.

## Usage

```bash
uv run track.py run --dry-run --limit 20   # preview 20 emails, writes nothing
uv run track.py run                        # update the sheet
uv run track.py new-season "Spring 2027" --start 2027-01-01 --end 2027-05-31
uv run track.py style                      # reapply formatting and rebuild the Stats tab
```

The first run scans from the season's start date. Later runs only look at new emails.

## Good to know

- **Read-only Gmail.** The script can't send, change or delete email.
- **Editing by hand is fine.** A row only changes when a new email for that application arrives, and stages only move forward.
- **Seasons.** A late reply to an old application updates its row in the old season's tab.
- **Re-applying.** A new confirmation more than 14 days after a rejection starts a new row.
- **Your own columns** go to the right of column I. Columns H–I (Thread IDs, Reached) are hidden and used by the script.
- **Login expiry.** While the OAuth app is in "Testing", Google expires the login every 7 days. The script reopens the browser when that happens.
- **Settings** such as `ghosted_days` and the Gmail search are in `config.yaml`.
- **Secrets stay local.** `credentials.json`, `token.json`, `.env` and `config.yaml` are gitignored.

## Cost

About $0.0002–0.0005 per email with Claude Haiku 5.5. The Gmail and Sheets APIs are free.

## Tests

```bash
uv run pytest
```
