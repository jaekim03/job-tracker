# job-tracker

Keeps a Google Sheet of your job applications up to date by reading your Gmail.

Each run finds recruiting emails, asks an AI model what each one means, and updates the sheet: one tab per recruiting season, one row per company and role.

| Company | Role | Stage | Date Applied | Last Update | Gmail Link | Notes |
|---|---|---|---|---|---|---|
| Acme | Software Engineer Intern | Interview | 2026-09-02 | 2026-09-20 | link | |

**Stages:** Applied → OA → Interview → Offer, plus Rejected, Withdrawn and Ghosted (no email for 60 days).

A **Stats** tab shows totals, OA and interview rates, offers, and a breakdown by stage. A **Pipeline** menu draws a flow chart of where your applications went.

## Setup

You need [uv](https://docs.astral.sh/uv/), a Google account, and an API key for an AI provider (or [Ollama](https://ollama.com) to run a model locally for free).

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
3. **Config**: create a blank Google Sheet, then copy the config and paste the sheet's link into `spreadsheet_id`.
   ```bash
   cp config.example.yaml config.yaml
   ```
4. **AI provider**: pick one in the `llm` section of `config.yaml` and put its key in `.env`.
   ```yaml
   llm:
     provider: anthropic        # see the table below
     model: claude-haiku-5-5    # any model your provider offers
   ```
   ```bash
   echo 'ANTHROPIC_API_KEY=...' > .env
   ```

   | `provider` | Key in `.env` |
   |---|---|
   | `anthropic` (default) | `ANTHROPIC_API_KEY` |
   | `openai` | `OPENAI_API_KEY` |
   | `gemini` | `GEMINI_API_KEY` |
   | `groq` | `GROQ_API_KEY` |
   | `openrouter` | `OPENROUTER_API_KEY` |
   | `ollama` (local, free) | none |
   | `openai-compatible` (any other server, set `base_url`) | `LLM_API_KEY` |

   A small, cheap model is plenty. With `anthropic`, `model` can be left out and defaults to `claude-haiku-5-5`.
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
uv run track.py run --quiet                # counts only, no company/role details
```

The first run scans from the season's start date. Later runs only look at new emails.

## Automate with GitHub Actions

The included workflow ([`.github/workflows/track.yml`](.github/workflows/track.yml)) runs the tracker every day at 15:00 UTC, so the sheet stays current without your computer on. On a public repo the logs are public, so on GitHub Actions the script prints counts only:

```
5 new emails · 1 added · 3 updated · 0 ghosted
```

1. **Keep your Google login from expiring.** In the Google Cloud console, open your OAuth consent screen (Google Auth Platform → Audience) and click **Publish app** to move it from Testing to **In production**. For personal use no review is needed. Then log in again, since logins made while in Testing still expire after 7 days:
   ```bash
   uv run track.py auth
   ```
2. **Upload your secrets** (encrypted by GitHub; nobody can read them back):
   ```bash
   gh secret set GOOGLE_CREDENTIALS < credentials.json
   gh secret set GOOGLE_TOKEN < token.json
   gh secret set CONFIG_YAML < config.yaml
   gh secret set ANTHROPIC_API_KEY
   ```
   The last command prompts for the key. Use your provider's key name if it isn't Anthropic (see the table above).
3. **Test it**: Actions tab → **Update tracker** → **Run workflow**, or:
   ```bash
   gh workflow run track.yml
   ```

Until the secrets are set, runs are skipped with a notice. If your Google login ever expires, the run fails with instructions: run `uv run track.py auth` locally and repeat the `GOOGLE_TOKEN` command. Using a fork? Enable Actions on it first, because GitHub turns off scheduled workflows in forks. GitHub also pauses schedules after 60 days without commits; re-enable them from the Actions tab.

## Good to know

- **Read-only Gmail.** The script can't send, change or delete email.
- **Editing by hand is fine.** A row only changes when a new email for that application arrives, and stages only move forward.
- **Seasons.** A late reply to an old application updates its row in the old season's tab.
- **Re-applying.** A new confirmation more than 14 days after a rejection starts a new row.
- **Your own columns** go to the right of column I. Columns H–I (Thread IDs, Reached) are hidden and used by the script.
- **Login expiry.** While the OAuth app is in "Testing", Google expires the login every 7 days. Locally the script reopens the browser; publishing the app (see above) stops the expiry.
- **Settings** such as `ghosted_days` and the Gmail search are in `config.yaml`.
- **Secrets stay local.** `credentials.json`, `token.json`, `.env` and `config.yaml` are gitignored.
- **Privacy.** See [PRIVACY.md](PRIVACY.md) for what's accessed and where data goes.

## Cost

The Gmail and Sheets APIs are free, so cost depends on the AI model. With Claude Haiku 5.5 it's about $0.0002–0.0005 per email, under $1 for a whole recruiting season. A local model through Ollama costs nothing, but runs slower (set `workers: 1` or `2`).

Each email is classified once and cached in `.cache/`, so reruns are free. Switching providers only affects new emails.

## Tests

```bash
uv run pytest
```
