"""Match classified emails to tracker rows and apply stage changes. Pure logic, no I/O."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

HEADERS = [
    "Company", "Role", "Stage", "Date Applied", "Last Update",
    "Gmail Link", "Notes", "Thread IDs",
]
THREAD_COL = HEADERS.index("Thread IDs")  # hidden in the sheet; only used for matching
STAGES = ["Applied", "OA", "Interview", "Offer", "Rejected", "Withdrawn", "Ghosted"]
PROGRESS_RANK = {"Applied": 0, "OA": 1, "Interview": 2, "Offer": 3}
TERMINAL = {"Rejected", "Withdrawn"}

_SUFFIXES = r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|plc|gmbh|the)\b"


@dataclass
class AppRow:
    tab: str
    row_num: Optional[int]  # 1-based sheet row; None = new, not yet written
    company: str = ""
    role: str = ""
    stage: str = ""
    date_applied: str = ""
    last_update: str = ""
    gmail_link: str = ""
    notes: str = ""
    thread_ids: list[str] = field(default_factory=list)
    dirty: bool = False

    @classmethod
    def from_values(cls, tab: str, row_num: int, values: list[str]) -> "AppRow":
        v = (values + [""] * len(HEADERS))[: len(HEADERS)]
        return cls(
            tab=tab, row_num=row_num, company=v[0], role=v[1], stage=v[2], date_applied=v[3],
            last_update=v[4], gmail_link=v[5],
            notes=v[6], thread_ids=[t for t in v[7].replace(" ", "").split(",") if t],
        )

    def to_values(self) -> list:
        return [
            self.company, self.role, self.stage, self.date_applied, self.last_update,
            self.gmail_link, self.notes, ",".join(self.thread_ids),
        ]


def normalize_company(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    s = re.sub(_SUFFIXES, " ", s)
    return re.sub(r"\s+", "", s)


_ROLE_NOISE = {
    "intern", "internship", "co", "op", "coop", "fall", "spring", "summer", "winter", "new", "grad",
    "graduate", "the", "and", "of", "for", "a", "an", "i", "ii", "iii", "remote", "hybrid", "onsite",
}


def _role_tokens(role: str) -> set[str]:
    out = set()
    for t in re.findall(r"[a-z]+", role.lower()):
        if t.endswith("ing") and len(t) > 6:
            t = t[:-3]  # engineering -> engineer
        elif t.endswith("s") and len(t) > 4:
            t = t[:-1]
        if t not in _ROLE_NOISE:
            out.add(t)
    return out


def role_match(a: str, b: str) -> bool:
    """Same role if titles share nearly all meaningful words (ignores intern/season/year noise)."""
    ta, tb = _role_tokens(a), _role_tokens(b)
    if not ta or not tb:
        return a.strip().lower() == b.strip().lower()
    return len(ta & tb) / len(ta | tb) >= 0.75


def parse_date(s: str) -> Optional[date]:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def find_row(rows: list[AppRow], company: str, role: str, thread_id: str) -> Optional[AppRow]:
    def compatible(r: AppRow) -> bool:
        return not role or not r.role or role_match(role, r.role)

    rows = rows[::-1]  # newest first: a re-application row wins over the older closed one
    # Same Gmail thread, unless the roles clearly differ (Gmail threads same-subject ATS emails together).
    for r in rows:
        if thread_id in r.thread_ids and compatible(r):
            return r
    key = normalize_company(company)
    if not key:
        return None
    same = [r for r in rows if normalize_company(r.company) == key]
    if not same:
        return None
    if role:
        exact = [r for r in same if r.role and role_match(role, r.role)]
        if exact:
            return exact[0]
        blank = [r for r in same if not r.role]
        return blank[0] if len(blank) == 1 else None
    open_rows = [r for r in same if r.stage not in TERMINAL]
    if len(open_rows) == 1:
        return open_rows[0]
    return same[0] if len(same) == 1 else None


def is_reapplication(row: AppRow, new_stage: str, email_date: date) -> bool:
    """A new 'Applied' email well after a closed application = a fresh application (e.g. next term's posting)."""
    if new_stage != "Applied" or row.stage not in TERMINAL:
        return False
    last = parse_date(row.last_update)
    return last is not None and email_date - last > timedelta(days=14)


def next_stage(current: str, new: str) -> str:
    """Stages only move forward; Rejected/Withdrawn are final; Ghosted revives on any new email."""
    if new == "Other":
        return current
    if not current or current == "Ghosted":
        return new
    if current in TERMINAL:
        return current
    if new in TERMINAL:
        return new
    if PROGRESS_RANK.get(new, -1) > PROGRESS_RANK.get(current, -1):
        return new
    return current


def apply_email(row: AppRow, cls, email) -> list[str]:
    """Update row in place from one classified email. Returns human-readable change notes."""
    changes = []
    d = f"{email.date:%Y-%m-%d}"
    stage = next_stage(row.stage, cls.stage)
    if stage != row.stage:
        changes.append(f"stage {row.stage or '-'} -> {stage}")
        row.stage = stage
    if cls.stage == "Applied" and not row.date_applied:
        row.date_applied = d
    if not row.company and cls.company:
        row.company = cls.company
    if not row.role and cls.role:
        row.role = cls.role
        changes.append(f"role = {cls.role}")
    last = parse_date(row.last_update)
    if last is None or email.date.date() >= last:
        row.last_update, row.gmail_link = d, email.link
    if email.thread_id not in row.thread_ids:
        row.thread_ids.append(email.thread_id)
    row.dirty = True
    return changes


def mark_ghosted(rows: list[AppRow], days: int, today: date) -> list[AppRow]:
    out = []
    for r in rows:
        if r.stage not in ("Applied", "OA"):
            continue
        last = parse_date(r.last_update) or parse_date(r.date_applied)
        if last and today - last > timedelta(days=days):
            r.stage, r.dirty = "Ghosted", True
            out.append(r)
    return out
