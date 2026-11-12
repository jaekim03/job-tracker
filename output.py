"""What the script prints. Quiet mode keeps email contents out of logs (e.g. public GitHub Actions logs)."""
import os

_quiet = False


def in_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true"


def set_quiet(value: bool) -> None:
    global _quiet
    _quiet = value


def is_quiet() -> bool:
    return _quiet


def detail(msg: str) -> None:
    """Lines that may contain email data (companies, roles, subjects). Hidden in quiet mode."""
    if not _quiet:
        print(msg)


def info(msg: str) -> None:
    """Lines that are safe anywhere: counts and setup messages."""
    print(msg)


def safe_error(e: BaseException) -> str:
    """Short description of an error with no message IDs, URLs or email text."""
    status = getattr(getattr(e, "resp", None), "status", None)          # googleapiclient HttpError
    status = status or getattr(getattr(e, "response", None), "status_code", None)  # gspread / httpx
    module = type(e).__module__.split(".")[0]
    source = {"googleapiclient": "Gmail API", "gspread": "Sheets API", "anthropic": "Anthropic API",
              "openai": "AI provider API", "google": "Google auth"}.get(module, type(e).__name__)
    hint = {401: "unauthorized", 403: "forbidden or rate limited", 404: "not found",
            429: "rate limited"}.get(int(status), "") if status else ""
    return " ".join(x for x in (source, "error", str(status) if status else "", f"({hint})" if hint else "") if x)
