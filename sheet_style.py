"""Look of the season tabs: builds Sheets API requests. Pure, no I/O."""
from matcher import HEADERS, STAGES, THREAD_COL

FONT = "Inter"
INK = "#202124"      # main text
MUTED = "#5f6368"    # headers, dates
FAINT = "#9aa0a6"    # closed applications
RULE = "#e8eaed"     # row separators
HEADER_RULE = "#bdc1c6"
LINK = "#1a73e8"

# stage -> (background, text)
STAGE_COLORS = {
    "Applied": ("#e8f0fe", "#1967d2"),
    "OA": ("#f3e8fd", "#8430ce"),
    "Interview": ("#fef7e0", "#b06000"),
    "Offer": ("#e6f4ea", "#137333"),
    "Rejected": ("#fce8e6", "#c5221f"),
    "Withdrawn": ("#f1f3f4", "#5f6368"),
    "Ghosted": ("#f1f3f4", "#80868b"),
}
CLOSED = ["Rejected", "Withdrawn", "Ghosted"]

COL = {name: i for i, name in enumerate(HEADERS)}
WIDTHS = {"Company": 200, "Role": 420, "Stage": 120, "Date Applied": 120, "Last Update": 120,
          "Gmail Link": 100, "Notes": 300}
HEADER_HEIGHT, ROW_HEIGHT = 40, 32


def _rgb(hex_color: str) -> dict:
    h = hex_color.lstrip("#")
    return {"rgbColor": {k: int(h[i:i + 2], 16) / 255 for k, i in (("red", 0), ("green", 2), ("blue", 4))}}


def _text(color: str, **extra) -> dict:
    return {"foregroundColorStyle": _rgb(color), **extra}


def season_tab_requests(sheet_id: int, row_count: int, existing_rules: int = 0) -> list[dict]:
    """Requests that (re)apply the full style to one season tab. Safe to run repeatedly."""
    n = len(HEADERS)

    def rng(r0, r1, c0, c1) -> dict:
        return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    def cells(r0, r1, c0, c1, fmt: dict, fields: str) -> dict:
        return {"repeatCell": {"range": rng(r0, r1, c0, c1), "cell": {"userEnteredFormat": fmt},
                               "fields": f"userEnteredFormat({fields})"}}

    def size(dimension: str, start: int, end: int, pixels: int) -> dict:
        return {"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": dimension, "startIndex": start, "endIndex": end},
            "properties": {"pixelSize": pixels}, "fields": "pixelSize"}}

    def col(name: str) -> tuple[int, int]:
        return COL[name], COL[name] + 1

    reqs: list[dict] = [
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"hideGridlines": True, "frozenRowCount": 1}},
            "fields": "gridProperties.hideGridlines,gridProperties.frozenRowCount"}},
        # Base look for every cell
        cells(0, row_count, 0, n,
              {"textFormat": _text(INK, fontFamily=FONT, fontSize=10, bold=False, underline=False),
               "verticalAlignment": "MIDDLE", "horizontalAlignment": "LEFT", "wrapStrategy": "CLIP",
               "backgroundColorStyle": _rgb("#ffffff"),
               "padding": {"left": 10, "right": 10, "top": 2, "bottom": 2}},
              "textFormat,verticalAlignment,horizontalAlignment,wrapStrategy,backgroundColorStyle,padding"),
        # Header
        cells(0, 1, 0, n, {"textFormat": _text(MUTED, fontFamily=FONT, fontSize=9, bold=True)}, "textFormat"),
        # Company stands out slightly; dates recede
        cells(1, row_count, *col("Company"),
              {"textFormat": _text(INK, fontFamily=FONT, fontSize=10, bold=True)}, "textFormat"),
        cells(1, row_count, COL["Date Applied"], COL["Last Update"] + 1,
              {"textFormat": _text(MUTED, fontFamily=FONT, fontSize=10)}, "textFormat"),
        cells(1, row_count, *col("Gmail Link"),
              {"textFormat": _text(LINK, fontFamily=FONT, fontSize=10, underline=False)}, "textFormat"),
        cells(1, row_count, *col("Notes"), {"wrapStrategy": "WRAP"}, "wrapStrategy"),
        cells(0, row_count, *col("Stage"), {"horizontalAlignment": "CENTER"}, "horizontalAlignment"),
        cells(1, row_count, *col("Stage"),
              {"textFormat": _text(INK, fontFamily=FONT, fontSize=9, bold=True)}, "textFormat"),
        # Lines: one under the header, hairlines between rows, nothing vertical
        {"updateBorders": {"range": rng(0, row_count, 0, n),
                           "top": {"style": "NONE"}, "left": {"style": "NONE"}, "right": {"style": "NONE"},
                           "innerVertical": {"style": "NONE"},
                           "innerHorizontal": {"style": "SOLID", "colorStyle": _rgb(RULE)},
                           "bottom": {"style": "SOLID", "colorStyle": _rgb(RULE)}}},
        {"updateBorders": {"range": rng(0, 1, 0, n),
                           "bottom": {"style": "SOLID", "colorStyle": _rgb(HEADER_RULE)}}},
        size("ROWS", 0, 1, HEADER_HEIGHT),
        size("ROWS", 1, row_count, ROW_HEIGHT),
        # Stage dropdown
        {"setDataValidation": {
            "range": rng(1, row_count, *col("Stage")),
            "rule": {"condition": {"type": "ONE_OF_LIST",
                                   "values": [{"userEnteredValue": s} for s in STAGES]},
                     "showCustomUi": True, "strict": False}}},
        # Thread IDs: needed for matching, not for reading
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": THREAD_COL, "endIndex": THREAD_COL + 1},
            "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
    ]
    reqs += [size("COLUMNS", COL[name], COL[name] + 1, px) for name, px in WIDTHS.items()]

    # Conditional colors: clear old rules, then add ours
    reqs += [{"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}} for _ in range(existing_rules)]
    stage_range = rng(1, row_count, *col("Stage"))
    rules = [
        {"ranges": [stage_range],
         "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": stage}]},
                         "format": {"backgroundColorStyle": _rgb(bg), "textFormat": _text(fg)}}}
        for stage, (bg, fg) in STAGE_COLORS.items()
    ]
    # Closed applications fade so open ones stand out
    stage_letter = chr(ord("A") + COL["Stage"])
    closed = ",".join(f'${stage_letter}2="{s}"' for s in CLOSED)
    rules.append({
        "ranges": [rng(1, row_count, 0, COL["Stage"]), rng(1, row_count, COL["Stage"] + 1, THREAD_COL)],
        "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                      "values": [{"userEnteredValue": f"=OR({closed})"}]},
                        "format": {"textFormat": _text(FAINT)}}})
    reqs += [{"addConditionalFormatRule": {"rule": rule, "index": i}} for i, rule in enumerate(rules)]
    return reqs


def plain_tab_requests(sheet_id: int, row_count: int, n_cols: int) -> list[dict]:
    """Lighter version of the same look for the Seasons tab."""
    whole = {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": row_count,
             "startColumnIndex": 0, "endColumnIndex": n_cols}
    header = {**whole, "endRowIndex": 1}
    return [
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"hideGridlines": True, "frozenRowCount": 1}},
            "fields": "gridProperties.hideGridlines,gridProperties.frozenRowCount"}},
        {"repeatCell": {"range": whole, "cell": {"userEnteredFormat": {
            "textFormat": _text(INK, fontFamily=FONT, fontSize=10, bold=False),
            "verticalAlignment": "MIDDLE", "padding": {"left": 10, "right": 10, "top": 2, "bottom": 2}}},
            "fields": "userEnteredFormat(textFormat,verticalAlignment,padding)"}},
        {"repeatCell": {"range": header, "cell": {"userEnteredFormat": {
            "textFormat": _text(MUTED, fontFamily=FONT, fontSize=9, bold=True)}},
            "fields": "userEnteredFormat(textFormat)"}},
        {"updateBorders": {"range": header, "bottom": {"style": "SOLID", "colorStyle": _rgb(HEADER_RULE)}}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": row_count},
            "properties": {"pixelSize": ROW_HEIGHT}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": n_cols},
            "properties": {"pixelSize": 140}, "fields": "pixelSize"}},
    ]
