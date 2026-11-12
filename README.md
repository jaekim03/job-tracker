# job-tracker

Scans Gmail for job application emails, classifies them with Claude Haiku, and keeps a Google Sheet up to date: one tab per recruiting season, one row per company + role.

Stages: Applied → OA → Interview → Offer, plus Rejected, Withdrawn, and Ghosted (no reply in 30 days).

## One-time setup

1. **Install [uv](https://docs.astral.sh/uv/)**, then `uv sync`.
2. **Google Cloud project** (console.cloud.google.com)
   - Create a project → *APIs & Services* → enable **Gmail API** and **Google Sheets API**.
   - *OAuth consent screen* → External → add your Gmail address as a **test user**.
   - *Credentials* → Create credentials → OAuth client ID → **Desktop app** → download JSON → save as `credentials.json` in this folder.
3. **Anthropic API key**: create one at platform.claude.com, then `echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env`
4. **Sheet**: create a blank Google Sheet, then `cp config.example.yaml config.yaml` and paste the sheet ID.
5. Log in and create the first season:
   ```bash
   uv run track.py auth
   uv run track.py new-season "Fall 2026" --start 2026-08-01 --end 2026-12-31
   ```

> While the OAuth app is in "Testing", Google expires the login every 7 days. The script just reopens the browser to log in again when that happens.

## Usage

```bash
uv run track.py run --dry-run --limit 20   # preview on 20 emails, writes nothing
uv run track.py run                        # update the sheet
uv run track.py new-season "Spring 2027" --start 2027-01-01 --end 2027-05-31
```

- Edit any row by hand. The script only changes a row when a new email for that application arrives, and stages only move forward.
- Late emails for an older season's application update that season's row; new applications go to the season containing the email date.
- Classifications are cached in `.cache/` so reruns don't cost API calls. Processed emails are logged in the hidden `_processed` tab.
- Only columns A–H are written (H, Thread IDs, is hidden and used for matching); add your own columns to the right.

## Cost

Claude Haiku 5.5 at low effort: roughly $0.0002–0.0005 per email. Gmail and Sheets APIs are free.

## Tests

```bash
uv run pytest
```
