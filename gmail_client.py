"""Search and fetch Gmail messages (read-only)."""
import base64
import html
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from googleapiclient.discovery import build

RETRIES = 8  # exponential backoff on Gmail rate-limit (403/429) and 5xx errors


@dataclass
class Email:
    id: str
    thread_id: str
    date: datetime
    sender: str
    subject: str
    body: str
    account: str = ""

    @property
    def link(self) -> str:
        return message_link(self.id, self.account)


def message_link(msg_id: str, account: str = "") -> str:
    """Gmail web link that opens in the given account, even if another account is signed in first."""
    if account:
        return f"https://mail.google.com/mail/?authuser={quote(account)}#all/{msg_id}"
    return f"https://mail.google.com/mail/#all/{msg_id}"


_MSG_ID_RE = re.compile(r"#(?:all|inbox)/([0-9a-f]+)$")


def message_id_from_link(url: str) -> str:
    m = _MSG_ID_RE.search(url or "")
    return m.group(1) if m else ""


def account_email(service) -> str:
    return service.users().getProfile(userId="me").execute(num_retries=RETRIES)["emailAddress"]


def gmail_service(creds):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def search(service, query: str) -> list[str]:
    ids, token = [], None
    while True:
        resp = service.users().messages().list(userId="me", q=query, pageToken=token, maxResults=500).execute(num_retries=RETRIES)
        ids += [m["id"] for m in resp.get("messages", [])]
        token = resp.get("nextPageToken")
        if not token:
            return ids


def fetch(service, msg_id: str, max_chars: int, account: str = "") -> Email:
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute(num_retries=RETRIES)
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    return Email(
        id=msg["id"],
        thread_id=msg["threadId"],
        date=datetime.fromtimestamp(int(msg["internalDate"]) / 1000),
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        body=_body_text(msg["payload"])[:max_chars],
        account=account,
    )


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _collect(part, mime: str) -> list[str]:
    out = []
    if part.get("mimeType") == mime and part.get("body", {}).get("data"):
        out.append(_decode(part["body"]["data"]))
    for sub in part.get("parts", []) or []:
        out += _collect(sub, mime)
    return out


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", raw)
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))


def _body_text(payload) -> str:
    plain = _collect(payload, "text/plain")
    text = "\n".join(plain) if plain else _strip_html("\n".join(_collect(payload, "text/html")))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()
