"""Classify recruiting emails with an LLM: Anthropic natively, or any OpenAI-compatible API."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from config import CACHE_DIR, LLMConfig
from gmail_client import Email

CACHE_FILE = CACHE_DIR / "classifications.json"

Stage = Literal["Applied", "OA", "Interview", "Offer", "Rejected", "Withdrawn", "Other"]


class Classification(BaseModel):
    is_application_email: bool = Field(
        description="True only if this email is about a specific job application of the recipient."
    )
    company: str = Field(description="Hiring company name, not the ATS vendor. Empty string if unknown.")
    role: str = Field(description="Job title as written in the email. Empty string if not mentioned.")
    stage: Stage


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


def _email_text(email: Email) -> str:
    return f"From: {email.sender}\nSubject: {email.subject}\nDate: {email.date:%Y-%m-%d}\n\n{email.body}"


def _warn(email: Email, msg: str) -> None:
    print(f"  ! {msg} on '{email.subject[:60]}'")


def _api_key(cfg: LLMConfig) -> Optional[str]:
    if not cfg.api_key_env:
        return None
    key = os.environ.get(cfg.api_key_env)
    if not key:
        raise SystemExit(f"Set {cfg.api_key_env} in .env for provider {cfg.provider}.")
    return key


def _anthropic_classifier(cfg: LLMConfig) -> Callable[[Email], Optional[Classification]]:
    import anthropic

    client = anthropic.Anthropic(api_key=_api_key(cfg))

    def classify(email: Email) -> Optional[Classification]:
        try:
            resp = client.messages.parse(
                model=cfg.model,
                max_tokens=2048,
                system=SYSTEM,
                messages=[{"role": "user", "content": _email_text(email)}],
                output_format=Classification,
                output_config={"effort": "low"},
            )
        except anthropic.APIStatusError as e:
            _warn(email, f"API error {e.status_code} {e.message}")
            return None
        except anthropic.APIConnectionError as e:
            _warn(email, f"Connection error {e}")
            return None
        if resp.stop_reason != "end_turn" or resp.parsed_output is None:
            _warn(email, f"No result (stop_reason={resp.stop_reason})")
            return None
        return resp.parsed_output

    return classify


def json_schema() -> dict:
    """Classification schema in the strict form OpenAI-style structured outputs expect."""
    schema = Classification.model_json_schema()
    schema["additionalProperties"] = False
    schema["required"] = list(schema["properties"])
    return schema


def parse_json_reply(text: str) -> Optional[Classification]:
    """Validate a model's JSON reply, tolerating ```json fences some models add."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.index("{"):] if "{" in text else text
    if "{" in text and "}" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    try:
        return Classification.model_validate_json(text)
    except ValidationError:
        return None


def _openai_classifier(cfg: LLMConfig) -> Callable[[Email], Optional[Classification]]:
    import openai

    client = openai.OpenAI(api_key=_api_key(cfg) or "not-needed", base_url=cfg.base_url)
    system = (SYSTEM + "\n\nReply with only a JSON object matching this schema:\n"
              + json.dumps(json_schema()))
    # Strict JSON-schema mode where the server supports it; plain JSON mode elsewhere.
    formats = [{"type": "json_schema", "json_schema": {"name": "classification", "schema": json_schema(),
                                                       "strict": True}},
               {"type": "json_object"}]
    state = {"format": 0}

    def classify(email: Email) -> Optional[Classification]:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": _email_text(email)}]
        while True:
            try:
                resp = client.chat.completions.create(
                    model=cfg.model, messages=messages, response_format=formats[state["format"]])
                break
            except openai.BadRequestError as e:
                if state["format"] + 1 < len(formats):
                    state["format"] += 1  # server doesn't support this response_format; fall back
                    continue
                _warn(email, f"API error {e.status_code} {e.message}")
                return None
            except openai.APIStatusError as e:
                _warn(email, f"API error {e.status_code} {e.message}")
                return None
            except openai.APIConnectionError as e:
                _warn(email, f"Connection error {e}")
                return None
        result = parse_json_reply(resp.choices[0].message.content if resp.choices else "")
        if result is None:
            _warn(email, "Reply wasn't valid JSON")
        return result

    return classify


def make_classifier(cfg: LLMConfig) -> Callable[[Email], Optional[Classification]]:
    return _anthropic_classifier(cfg) if cfg.provider == "anthropic" else _openai_classifier(cfg)


def classify_all(emails: list[Email], workers: int, llm: LLMConfig) -> dict[str, Optional[Classification]]:
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
        print(f"Classifying {len(todo)} emails with {llm.provider}/{llm.model} "
              f"({len(emails) - len(todo)} cached)...")
        classify = make_classifier(llm)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, (e, c) in enumerate(zip(todo, pool.map(classify, todo)), 1):
                results[e.id] = c
                if c is not None:
                    cache[e.id] = c.model_dump()
                if i % 25 == 0:
                    print(f"  {i}/{len(todo)}")
                    _save_cache(cache)
        _save_cache(cache)
    return results
