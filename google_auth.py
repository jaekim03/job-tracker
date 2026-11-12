"""Google OAuth shared by Gmail (read-only) and Sheets."""
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import CREDENTIALS_PATH, TOKEN_PATH
from output import in_ci

RELOGIN_HELP = ("Google login is missing or expired, and there's no browser here to log in. "
                "On your computer run `uv run track.py auth`, then update the secret: "
                "gh secret set GOOGLE_TOKEN < token.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]


def get_credentials(force_login: bool = False) -> Credentials:
    creds = None
    if TOKEN_PATH.exists() and not force_login:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
            return creds
        except RefreshError:
            if in_ci():
                raise SystemExit(RELOGIN_HELP)
            print("Google login expired; opening browser to log in again.")
    if in_ci():
        raise SystemExit(RELOGIN_HELP)
    if not CREDENTIALS_PATH.exists():
        raise SystemExit("credentials.json not found. See README > One-time setup.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())
    return creds
