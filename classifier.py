"""Classify recruiting emails with Claude Haiku (structured output)."""
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, Field

from config import CACHE_DIR
from gmail_client import Email

MODEL = "claude-haiku-5-5"
CACHE_FILE = CACHE_DIR / "classifications.json"

Stage = Literal["Applied", "OA", "Interview", "Offer", "Rejected", "Withdrawn", "Other"]


class Classification(BaseModel):
    is_application_email: bool = Field(
        description="True only if this email is about a specific job application of the recipient."
    )
    company: str = Field(description="Hiring company name, not the ATS vendor. Empty string if unknown.")
    role: str = Field(description="Job title as written in the email. Empty string if not mentioned.")
    stage: Stage
    confidence: float = Field(description="0.0-1.0 confidence in company + stage.")


SYSTEM = """You classify emails in a job seeker's inbox for an application tracker.

is_application_email = true only for emails about one of the recipient's own applications:
confirmations, assessments, interview invites/scheduling, offers, rejections, withdrawal confirmations.
false for job alerts, job board digests, newsletters, recruiter cold outreach about roles the
recipient has not applied to, marketing, and networking/event emails.

stage:
- Applied: application received/submitted confirmation.
- OA: online assessment, coding challenge, take-home, HireVue/video screen, skills test.
- Interview: invitation to or scheduling of any interview or phone screen (recruiter screen counts).
- Offer: job offer extended.
- Rejected: not moving forward, position filled, decided on other candidates.
- Withdrawn: confirms the candidate withdrew.
- Other: about an application but none of the above (e.g. generic status ping, document request).

company: the employer, never the ATS (Greenhouse, Lever, Workday, Ashby, iCIMS, etc.).
Strip suffixes like Inc./LLC. If is_application_email is false, use stage "Other" and empty strings."""


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache))


def _classify_one(client: anthropic.Anthropic, email: Email) -> Optional[Classification]:
    content = (
        f"From: {email.sender}\nSubject: {email.subject}\nDate: {email.date:%Y-%m-%d}\n\n{email.body}"
    )
    try:
        resp = client.messages.parse(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_format=Classification,
            output_config={"effort": "low"},
        )
    except anthropic.APIStatusError as e:
        print(f"  ! Claude error on '{email.subject[:60]}': {e.status_code} {e.message}")
        return None
    except anthropic.APIConnectionError as e:
        print(f"  ! Connection error on '{email.subject[:60]}': {e}")
        return None
    if resp.stop_reason != "end_turn" or resp.parsed_output is None:
        print(f"  ! Could not classify '{email.subject[:60]}' (stop_reason={resp.stop_reason})")
        return None
    return resp.parsed_output


def classify_all(emails: list[Email], workers: int) -> dict[str, Optional[Classification]]:
    """Returns {message_id: Classification or None}. Results are cached on disk so reruns are free."""
    cache = _load_cache()
    results: dict[str, Optional[Classification]] = {}
    todo = []
    for e in emails:
        if e.id in cache:
            results[e.id] = Classification(**cache[e.id])
        else:
            todo.append(e)
    if todo:
        print(f"Classifying {len(todo)} emails with {MODEL} ({len(emails) - len(todo)} cached)...")
        client = anthropic.Anthropic()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, (e, c) in enumerate(zip(todo, pool.map(lambda em: _classify_one(client, em), todo)), 1):
                results[e.id] = c
                if c is not None:
                    cache[e.id] = c.model_dump()
                if i % 25 == 0:
                    print(f"  {i}/{len(todo)}")
                    _save_cache(cache)
        _save_cache(cache)
    return results
