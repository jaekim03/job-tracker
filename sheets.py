"""Google Sheets storage: Seasons tab, one tab per season, hidden _processed tab."""
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import gspread
from gspread.utils import ValueRenderOption

from matcher import HEADERS, AppRow, parse_date
from sheet_style import (STATS_COLS, STATS_TAB, plain_tab_requests, season_tab_requests, stats_tab_requests,
                         stats_values)

SEASONS_TAB = "Seasons"
PROCESSED_TAB = "_processed"
SEASON_HEADERS = ["Name", "Start", "End", "Active"]
PROCESSED_HEADERS = ["Message ID", "Email Date", "Processed At", "Result"]
RESERVED = {SEASONS_TAB, PROCESSED_TAB, STATS_TAB}
LINK_COL = HEADERS.index("Gmail Link")
LINK_LABEL = "Open"
_LINK_RE = re.compile(r'HYPERLINK\(\s*"([^"]+)"', re.I)


def _letter(col: int) -> str:
    return chr(ord("A") + col)


LAST_COL = _letter(len(HEADERS) - 1)


def link_url(cell: str) -> str:
    """URL from a link cell, whether it holds =HYPERLINK("url","Open") or a bare URL."""
    m = _LINK_RE.search(cell or "")
    if m:
        return m.group(1)
    cell = (cell or "").strip()
    return cell if cell.lower().startswith("http") else ""


def link_formula(url: str) -> str:
    """Short clickable label instead of a long URL."""
    return f'=HYPERLINK("{url}","{LINK_LABEL}")' if url and '"' not in url else url


def _has_data(values: list[str]) -> bool:
    """A row counts as filled if Company, Role, or Stage is set (ignores stray values in other columns)."""
    v = values + ["", "", ""]
    return any(c.strip() for c in v[:3])


@dataclass
class Season:
    name: str
    start: date
    end: Optional[date]
    active: bool

    def contains(self, d: date) -> bool:
        return self.start <= d and (self.end is None or d <= self.end)


class Store:
    def __init__(self, creds, spreadsheet_id: str):
        self.sh = gspread.authorize(creds).open_by_key(spreadsheet_id)
        self._titles = {ws.title for ws in self.sh.worksheets()}

    # ---- setup -------------------------------------------------------------
    def _ensure_tab(self, title: str, headers: list[str], hidden: bool = False):
        if title in self._titles:
            return self.sh.worksheet(title)
        ws = self.sh.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.update(range_name="A1", values=[headers])
        ws.freeze(rows=1)
        if hidden:
            ws.hide()
        self._titles.add(title)
        return ws

    def ensure_schema(self) -> None:
        """Bring older season tabs up to the current HEADERS (adds new columns at the end)."""
        for s in self.seasons():
            if s.name not in self._titles:
                continue
            ws = self.sh.worksheet(s.name)
            head = ws.row_values(1)
            if head == HEADERS:
                continue
            if head != HEADERS[: len(head)]:
                raise SystemExit(f"Tab '{s.name}' has unexpected headers {head}; fix row 1 by hand.")
            if ws.col_count < len(HEADERS):
                ws.add_cols(len(HEADERS) - ws.col_count)
            ws.update(range_name="A1", values=[HEADERS])

    def apply_style(self) -> list[str]:
        """(Re)apply the look to every season tab and the Seasons tab; active season goes first."""
        self.ensure_schema()
        meta = self.sh.fetch_sheet_metadata(
            {"fields": "sheets(properties(sheetId),conditionalFormats)"})
        rule_counts = {s["properties"]["sheetId"]: len(s.get("conditionalFormats", []))
                       for s in meta["sheets"]}
        seasons = [s for s in self.seasons() if s.name in self._titles]
        reqs, styled = [], []
        for s in seasons:
            ws = self.sh.worksheet(s.name)
            reqs += season_tab_requests(ws.id, ws.row_count, rule_counts.get(ws.id, 0))
            styled.append(s.name)
        if SEASONS_TAB in self._titles:
            ws = self.sh.worksheet(SEASONS_TAB)
            reqs += plain_tab_requests(ws.id, ws.row_count, len(SEASON_HEADERS))
        active = next((s for s in seasons if s.active), None)
        if active:
            reqs.append({"updateSheetProperties": {
                "properties": {"sheetId": self.sh.worksheet(active.name).id, "index": 0},
                "fields": "index"}})
        if active:
            stats = self._ensure_stats(active.name)
            reqs += stats_tab_requests(stats.id, stats.row_count)
            reqs.append({"updateSheetProperties": {
                "properties": {"sheetId": stats.id, "index": 1}, "fields": "index"}})
        if reqs:
            self.sh.batch_update({"requests": reqs})
        return styled

    def _ensure_stats(self, default_season: str):
        """Create or refresh the Stats tab, keeping whichever season is picked in B2."""
        names = {s.name for s in self.seasons()}
        if STATS_TAB in self._titles:
            ws = self.sh.worksheet(STATS_TAB)
            picked = (ws.acell("B2").value or "").strip()
        else:
            ws = self.sh.add_worksheet(title=STATS_TAB, rows=30, cols=STATS_COLS)
            self._titles.add(STATS_TAB)
            picked = ""
        grid = stats_values()
        grid[1][1] = picked if picked in names else default_season
        ws.batch_clear([f"A1:{_letter(STATS_COLS - 1)}{ws.row_count}"])
        ws.update(range_name="A1", values=grid, value_input_option="USER_ENTERED")
        return ws

    # ---- seasons -----------------------------------------------------------
    def seasons(self) -> list[Season]:
        if SEASONS_TAB not in self._titles:
            return []
        out = []
        for v in self.sh.worksheet(SEASONS_TAB).get_all_values()[1:]:
            v = (v + ["", "", "", ""])[:4]
            start = parse_date(v[1])
            if v[0] and start:
                out.append(Season(v[0], start, parse_date(v[2]), v[3].strip().upper() == "TRUE"))
        return out

    def create_season(self, name: str, start: date, end: Optional[date]) -> None:
        if name in RESERVED:
            raise SystemExit(f"'{name}' is a reserved tab name.")
        existing = self.seasons()
        if any(s.name == name for s in existing):
            raise SystemExit(f"Season '{name}' already exists.")
        ws_seasons = self._ensure_tab(SEASONS_TAB, SEASON_HEADERS)
        rows = []
        for s in existing:
            s_end = s.end
            if s.active and s_end is None:
                s_end = date.fromordinal(start.toordinal() - 1)
            rows.append([s.name, s.start.isoformat(), s_end.isoformat() if s_end else "", False])
        rows.append([name, start.isoformat(), end.isoformat() if end else "", True])
        ws_seasons.update(range_name="A2", values=rows, value_input_option="RAW")
        self._ensure_tab(name, HEADERS)
        self._ensure_tab(PROCESSED_TAB, PROCESSED_HEADERS, hidden=True)
        self.apply_style()

    # ---- rows --------------------------------------------------------------
    def load_rows(self, seasons: list[Season]) -> list[AppRow]:
        rows = []
        for s in seasons:
            if s.name not in self._titles:
                continue
            ws = self.sh.worksheet(s.name)
            values = ws.get_all_values()
            # The link column shows a short label; the URL lives in the cell's formula.
            col = _letter(LINK_COL)
            formulas = ws.get(f"{col}1:{col}", value_render_option=ValueRenderOption.formula)
            for i, v in enumerate(values[1:], start=2):
                if _has_data(v):
                    row = AppRow.from_values(s.name, i, v)
                    cell = formulas[i - 1][0] if i - 1 < len(formulas) and formulas[i - 1] else ""
                    row.gmail_link = link_url(str(cell))
                    rows.append(row)
        return rows

    def _next_free_row(self, ws) -> int:
        values = ws.get_all_values()
        last = max((i for i, v in enumerate(values[1:], start=2) if _has_data(v)), default=1)
        return last + 1

    def save_rows(self, rows: list[AppRow]) -> None:
        by_tab: dict[str, list[AppRow]] = {}
        for r in rows:
            if r.dirty:
                by_tab.setdefault(r.tab, []).append(r)
        for tab, tab_rows in by_tab.items():
            ws = self.sh.worksheet(tab)
            new = [r for r in tab_rows if not r.row_num]
            if new:
                # Write explicitly after the last real row rather than relying on append_rows,
                # which is thrown off by stray values or validation in otherwise empty rows.
                start = self._next_free_row(ws)
                end = start + len(new) - 1
                if end > ws.row_count:
                    ws.add_rows(end - ws.row_count + 100)
                for i, r in enumerate(new):
                    r.row_num = start + i
            # Text goes in as-is (RAW); only the link cell is a formula (USER_ENTERED).
            before, link, after = _letter(LINK_COL - 1), _letter(LINK_COL), _letter(LINK_COL + 1)
            raw, links = [], []
            for r in tab_rows:
                v, n = r.to_values(), r.row_num
                raw.append({"range": f"A{n}:{before}{n}", "values": [v[:LINK_COL]]})
                raw.append({"range": f"{after}{n}:{LAST_COL}{n}", "values": [v[LINK_COL + 1:]]})
                links.append({"range": f"{link}{n}", "values": [[link_formula(v[LINK_COL])]]})
            ws.batch_update(raw, value_input_option="RAW")
            ws.batch_update(links, value_input_option="USER_ENTERED")

    # ---- processed log -----------------------------------------------------
    def processed(self) -> dict[str, date]:
        """{message_id: email_date} of every email already handled."""
        if PROCESSED_TAB not in self._titles:
            return {}
        out = {}
        for v in self.sh.worksheet(PROCESSED_TAB).get_all_values()[1:]:
            if v and v[0]:
                out[v[0]] = parse_date(v[1] if len(v) > 1 else "") or date.min
        return out

    def log_processed(self, entries: list[tuple[str, date, str]]) -> None:
        if not entries:
            return
        ws = self._ensure_tab(PROCESSED_TAB, PROCESSED_HEADERS, hidden=True)
        now = datetime.now().isoformat(timespec="seconds")
        ws.append_rows([[mid, d.isoformat(), now, res] for mid, d, res in entries],
                       value_input_option="RAW", table_range="A1")
