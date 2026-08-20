"""
Extract economic return per mREIT from "BV Historical Data.xlsx":
    data/ecn_return_quarterly.csv  -- ticker, quarter, quarter_end, ecn_return
        (one row per ticker per quarter, straight from the "Ecn Retn" columns)
    data/ecn_return_trailing.csv   -- ticker, as_of_quarter, return_1y, return_2y,
        return_3y, return_4y (one row per ticker, straight from the workbook's
        own "1/2/3/4-Year Ecn Return" columns)

These trailing figures are taken AS-IS from the workbook rather than recomputed
by compounding the quarterly series ourselves: a geometric-compounding check
(product of the trailing N*4 quarterly returns) reproduces the workbook's
1-Year figure exactly for every ticker, but diverges meaningfully at 2/3/4
years -- so the workbook's own multi-year methodology isn't plain quarterly
compounding, and rather than guess at it, we just trust the source numbers.
This does mean these four columns are only as current as the workbook / the
last extraction -- there's no mechanism yet to roll them forward as new
quarters are added (unlike book value's "Update Book Values" tab).

Same locked-OneDrive-file workaround as extract_bv.py (copy to temp, then read).
Run this again any time the source workbook is updated.
"""
import shutil
import tempfile
from pathlib import Path

import openpyxl

from common import ECN_RETURN_QUARTERLY_CSV, ECN_RETURN_TRAILING_CSV, QUARTER_ENDS, SOURCE_XLSX, normalize_quarter_label

SHEET_NAME = "mREITs"
TICKER_COL = 2           # column B
FIRST_ECN_COL = 25       # column Y (Q2'21 economic return)
NUM_QUARTERS = len(QUARTER_ENDS)
TRAILING_COLS = {1: 46, 2: 47, 3: 48, 4: 49}  # columns AT..AW: 1/2/3/4-Year Ecn Return
LATEST_QUARTER = list(QUARTER_ENDS.keys())[-1]  # the quarter AT:AW are computed "as of"
HEADER_ROW = 2
FIRST_DATA_ROW = 3


def load_workbook_safely(path: Path):
    """Copy the (possibly locked) workbook to a temp file, then load it."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / path.name
        shutil.copy2(path, tmp_path)
        return openpyxl.load_workbook(tmp_path, data_only=True)


def main():
    wb = load_workbook_safely(SOURCE_XLSX)
    ws = wb[SHEET_NAME]

    header_labels = []
    for c in range(FIRST_ECN_COL, FIRST_ECN_COL + NUM_QUARTERS):
        raw = ws.cell(row=HEADER_ROW, column=c).value
        header_labels.append(normalize_quarter_label(raw))
    expected = list(QUARTER_ENDS.keys())
    if header_labels != expected:
        raise ValueError(
            f"Ecn Retn quarter headers in workbook don't match common.QUARTER_ENDS.\n"
            f"Workbook: {header_labels}\nExpected: {expected}\n"
            "Update scripts/common.py QUARTER_ENDS if the workbook added new quarters."
        )

    quarterly_rows = []
    trailing_rows = []
    r = FIRST_DATA_ROW
    while True:
        ticker = ws.cell(row=r, column=TICKER_COL).value
        if ticker is None:
            break
        ticker = str(ticker).strip().upper()
        for i, quarter in enumerate(expected):
            ret = ws.cell(row=r, column=FIRST_ECN_COL + i).value
            if ret is None:
                continue
            quarterly_rows.append(
                {
                    "ticker": ticker,
                    "quarter": quarter,
                    "quarter_end": QUARTER_ENDS[quarter],
                    # Rounded to avoid float-repr jitter on re-extraction if Excel
                    # recalculates the source formulas (see extract_bv.py).
                    "ecn_return": round(float(ret), 6),
                }
            )

        trailing = {years: ws.cell(row=r, column=col).value for years, col in TRAILING_COLS.items()}
        trailing_rows.append(
            {
                "ticker": ticker,
                "as_of_quarter": LATEST_QUARTER,
                "return_1y": round(trailing[1], 6) if trailing[1] is not None else None,
                "return_2y": round(trailing[2], 6) if trailing[2] is not None else None,
                "return_3y": round(trailing[3], 6) if trailing[3] is not None else None,
                "return_4y": round(trailing[4], 6) if trailing[4] is not None else None,
            }
        )
        r += 1

    ECN_RETURN_QUARTERLY_CSV.parent.mkdir(exist_ok=True)
    with open(ECN_RETURN_QUARTERLY_CSV, "w", newline="", encoding="utf-8") as f:
        f.write("ticker,quarter,quarter_end,ecn_return\n")
        for row in quarterly_rows:
            f.write(f"{row['ticker']},{row['quarter']},{row['quarter_end']},{row['ecn_return']}\n")

    with open(ECN_RETURN_TRAILING_CSV, "w", newline="", encoding="utf-8") as f:
        f.write("ticker,as_of_quarter,return_1y,return_2y,return_3y,return_4y\n")
        for row in trailing_rows:
            f.write(
                f"{row['ticker']},{row['as_of_quarter']},"
                f"{row['return_1y']},{row['return_2y']},{row['return_3y']},{row['return_4y']}\n"
            )

    tickers = sorted({row["ticker"] for row in quarterly_rows})
    print(f"Extracted {len(quarterly_rows)} (ticker, quarter) economic-return rows for {len(tickers)} tickers.")
    print(f"Saved quarterly series to {ECN_RETURN_QUARTERLY_CSV}")
    print(f"Saved trailing 1/2/3/4-year returns (as of {LATEST_QUARTER}) to {ECN_RETURN_TRAILING_CSV}")


if __name__ == "__main__":
    main()
