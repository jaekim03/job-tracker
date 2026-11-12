"""Google Sheets storage: Seasons tab, one tab per season, hidden _processed tab."""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import gspread

from matcher import HEADERS, STAGES, THREAD_COL, AppRow, parse_date

SEASONS_TAB = "Seasons"
PROCESSED_TAB = "_processed"
SEASON_HEADERS = ["Name", "Start", "End", "Active"]
PROCESSED_HEADERS = ["Message ID", "Email Date", "Processed At", "Result"]
RESERVED = {SEASONS_TAB, PROCESSED_TAB}
LAST_COL = chr(ord("A") + len(HEADERS) - 1)


def _has_data(values: list[str]) -> bool:
    """A row counts as filled if Company, Role, or Stage is set (checkbox columns alone read as FALSE)."""
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
        ws.format("1:1", {"textFormat": {"bold": True}})
        if hidden:
            ws.hide()
        self._titles.add(title)
        return ws

    def _format_season_tab(self, ws) -> None:
        def col_range(col: int) -> dict:
            return {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": 1000,
                    "startColumnIndex": col, "endColumnIndex": col + 1}

        stage_rule = {"condition": {"type": "ONE_OF_LIST",
                                    "values": [{"userEnteredValue": s} for s in STAGES]},
                      "showCustomUi": True, "strict": False}
        checkbox = {"condition": {"type": "BOOLEAN"}}
        self.sh.batch_update({"requests": [
            {"setDataValidation": {"range": col_range(2), "rule": stage_rule}},
            {"setDataValidation": {"range": col_range(HEADERS.index("Locked")), "rule": checkbox}},
            {"setDataValidation": {"range": col_range(HEADERS.index("Needs Review")), "rule": checkbox}},
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                          "startIndex": THREAD_COL, "endIndex": THREAD_COL + 1},
                "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
        ]})

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
        ws = self._ensure_tab(name, HEADERS)
        self._format_season_tab(ws)
        self._ensure_tab(PROCESSED_TAB, PROCESSED_HEADERS, hidden=True)

    # ---- rows --------------------------------------------------------------
    def load_rows(self, seasons: list[Season]) -> list[AppRow]:
        rows = []
        for s in seasons:
            if s.name not in self._titles:
                continue
            values = self.sh.worksheet(s.name).get_all_values()
            for i, v in enumerate(values[1:], start=2):
                if _has_data(v):
                    rows.append(AppRow.from_values(s.name, i, v))
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
            updates = [{"range": f"A{r.row_num}:{LAST_COL}{r.row_num}", "values": [r.to_values()]}
                       for r in tab_rows if r.row_num]
            if updates:
                ws.batch_update(updates, value_input_option="RAW")
            new = [r for r in tab_rows if not r.row_num]
            if new:
                # Write explicitly after the last real row: append_rows would skip past
                # empty-but-checkbox rows (they read as FALSE) to the bottom of the sheet.
                start = self._next_free_row(ws)
                end = start + len(new) - 1
                if end > ws.row_count:
                    ws.add_rows(end - ws.row_count + 100)
                ws.update(range_name=f"A{start}:{LAST_COL}{end}", values=[r.to_values() for r in new],
                          value_input_option="RAW")
                for i, r in enumerate(new):
                    r.row_num = start + i

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
