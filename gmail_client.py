"""Search and fetch Gmail messages (read-only)."""
import base64
import html
import re
from dataclasses import dataclass
from datetime import datetime

from googleapiclient.discovery import build


@dataclass
class Email:
    id: str
    thread_id: str
    date: datetime
    sender: str
    subject: str
    body: str

    @property
    def link(self) -> str:
        return f"https://mail.google.com/mail/u/0/#all/{self.id}"


def gmail_service(creds):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def search(service, query: str) -> list[str]:
    ids, token = [], None
    while True:
        resp = service.users().messages().list(userId="me", q=query, pageToken=token, maxResults=500).execute()
        ids += [m["id"] for m in resp.get("messages", [])]
        token = resp.get("nextPageToken")
        if not token:
            return ids


def fetch(service, msg_id: str, max_chars: int) -> Email:
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    return Email(
        id=msg["id"],
        thread_id=msg["threadId"],
        date=datetime.fromtimestamp(int(msg["internalDate"]) / 1000),
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        body=_body_text(msg["payload"])[:max_chars],
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
