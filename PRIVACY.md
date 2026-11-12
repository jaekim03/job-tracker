# Privacy Policy

_Last updated: November 12, 2026_

job-tracker is an open-source script that you run yourself, on your own computer or in your own GitHub Actions. It has no server, and its author never receives any of your data.

## What it accesses

| Google permission | What it's used for |
|---|---|
| Gmail, **read-only** (`gmail.readonly`) | Searching for and reading job-application emails. It can't send, change or delete email. |
| Google Sheets (`spreadsheets`) | Reading and updating the one spreadsheet you name in `config.yaml`. |

## Where your data goes

- **Your AI provider.** For each candidate email, the sender, subject, date and the first 4,000 characters of the body are sent to the AI provider you configure (Anthropic by default; you may choose another or a local model) to identify the company, role and stage. That provider handles the data under its own privacy policy.
- **Your Google Sheet.** The results (company, role, stage, dates, a link to the email) are written to your own spreadsheet.
- **Your computer.** Your Google login (`token.json`) and a cache of results (`.cache/`) are stored locally. Email bodies are not saved.
- **Your GitHub secrets, only if you enable the GitHub Actions workflow.** Your login and config are stored as encrypted repository secrets you control.

Nothing is sold, shared for advertising, or sent anywhere else.

## Google API data

job-tracker's use and transfer of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

## Removing access

- Revoke access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
- Delete `token.json` and `.cache/` from your computer, and any GitHub secrets you created.

## Contact

Open an issue at [github.com/jaekim03/job-tracker/issues](https://github.com/jaekim03/job-tracker/issues).
