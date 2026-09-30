"""Shared constants and paths for the mREITs P/BV project."""
import re
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

SOURCE_XLSX = PROJECT_ROOT / "BV Historical Data.xlsx"

BV_QUARTERLY_CSV = DATA_DIR / "bv_quarterly.csv"
PRICES_DAILY_CSV = DATA_DIR / "prices_daily.csv"
PBV_DAILY_CSV = DATA_DIR / "pbv_daily.csv"
ECN_RETURN_QUARTERLY_CSV = DATA_DIR / "ecn_return_quarterly.csv"
DIVIDENDS_CSV = DATA_DIR / "dividends.csv"
BV_ESTIMATES_CSV = DATA_DIR / "bv_estimates.csv"

# Ordered list of quarter labels as they appear (normalized) in the workbook,
# Q2'21 through Q2'26, mapped to their calendar quarter-end date.
QUARTER_ENDS = {
    "Q2'21": "2021-06-30",
    "Q3'21": "2021-09-30",
    "Q4'21": "2021-12-31",
    "Q1'22": "2022-03-31",
    "Q2'22": "2022-06-30",
    "Q3'22": "2022-09-30",
    "Q4'22": "2022-12-31",
    "Q1'23": "2023-03-31",
    "Q2'23": "2023-06-30",
    "Q3'23": "2023-09-30",
    "Q4'23": "2023-12-31",
    "Q1'24": "2024-03-31",
    "Q2'24": "2024-06-30",
    "Q3'24": "2024-09-30",
    "Q4'24": "2024-12-31",
    "Q1'25": "2025-03-31",
    "Q2'25": "2025-06-30",
    "Q3'25": "2025-09-30",
    "Q4'25": "2025-12-31",
    "Q1'26": "2026-03-31",
    "Q2'26": "2026-06-30",
}

QUARTER_ORDER = list(QUARTER_ENDS.keys())

# Reverse stock splits. yfinance retroactively restates ALL historical prices for a
# split (so our whole daily price series is already on the POST-split share count),
# but the workbook's book-value-per-share only switches to the post-split scale
# starting the quarter the split actually shows up in its filings. Any BV quarter
# still on the old (pre-split) scale needs to be multiplied by `ratio` so it's
# comparable to the (always post-split) prices -- otherwise P/BV is inflated by
# roughly `ratio`x for every quarter that uses a pre-split BV as its lagged divisor.
#
# `last_pre_split_quarter` is picked by where the BV series itself jumps to the new
# scale, not by comparing quarter-end to the split date: ARR's Q3'23 book value
# (quarter-end 9/30/23) was already reported on a post-split basis even though the
# actual 1:5 split (10/2/23) landed a couple of days after quarter-end.
SPLITS = {
    "CIM": {"ratio": 3, "split_date": "2024-05-22", "last_pre_split_quarter": "Q1'24"},
    "ARR": {"ratio": 5, "split_date": "2023-10-02", "last_pre_split_quarter": "Q2'23"},
}


def normalize_quarter_label(raw: str) -> str:
    """Turn workbook header variants like "Q2' 21 " into "Q2'21"."""
    return raw.replace(" ", "").strip()


_QUARTER_MONTH_DAY = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
_QUARTER_LABEL_RE = re.compile(r"^Q([1-4])'(\d{2})$")


def quarter_end_date(label: str) -> str:
    """"Q3'26" -> "2026-09-30". Computed from the label itself, so it works for
    ANY quarter -- including ones reported after the workbook was built, not
    just the fixed set in QUARTER_ENDS above."""
    m = _QUARTER_LABEL_RE.match(label)
    if not m:
        raise ValueError(f"Bad quarter label: {label!r} (expected e.g. \"Q3'26\")")
    q, yy = int(m.group(1)), int(m.group(2))
    month, day = _QUARTER_MONTH_DAY[q]
    return f"{2000 + yy}-{month:02d}-{day:02d}"


def sorted_quarters(labels) -> list[str]:
    """Chronologically sort (and dedupe) any collection of quarter labels."""
    return sorted(set(labels), key=quarter_end_date)


def prior_quarter_in(known_quarters, label: str) -> str | None:
    """Return the quarter label immediately before `label` within
    `known_quarters` (any collection), or None if it's the earliest."""
    ordered = sorted_quarters(known_quarters)
    idx = ordered.index(label)
    return ordered[idx - 1] if idx > 0 else None


def next_quarter_label(label: str) -> str:
    """"Q2'26" -> "Q3'26", "Q4'25" -> "Q1'26". Used to name the in-progress
    quarter that comes after the last quarter present in the workbook."""
    q = int(label[1])
    yy = int(label[3:])
    q += 1
    if q > 4:
        q = 1
        yy += 1
    return f"Q{q}'{yy:02d}"


def trailing_return(returns: dict, known_quarters, as_of_quarter: str, years: int):
    """Trailing N-year economic return as of `as_of_quarter`: compounds the
    last (years * 4) quarterly returns, INCLUDING as_of_quarter itself,
    product(1 + r) - 1. `returns` maps quarter label -> that ticker's
    quarterly return; `known_quarters` is the chronological universe of
    quarters to count the window against.

    Note: the workbook's own 2/3/4-Year Ecn Return columns actually exclude
    the latest quarter (their window ends one quarter early -- confirmed
    cell-by-cell), while its 1-Year column includes it. That asymmetry is
    treated here as a workbook quirk, not something to reproduce: every
    horizon uses the same "ends at as_of_quarter" convention as 1-year, so
    e.g. the 2-Year figure as of Q2'26 compounds Q3'24..Q2'26, not
    Q2'24..Q1'26. Values will therefore differ slightly from the workbook's
    own 2/3/4-Year columns.

    Returns None if the window extends before the start of `known_quarters`,
    or any quarter in it is missing a return for this ticker (e.g. the
    ticker didn't exist yet)."""
    ordered = sorted_quarters(known_quarters)
    if as_of_quarter not in ordered:
        return None
    idx = ordered.index(as_of_quarter)
    n = years * 4
    start = idx - n + 1
    if start < 0:
        return None
    window = ordered[start : idx + 1]
    values = [returns.get(q) for q in window]
    if any(v is None for v in values):
        return None
    product = 1.0
    for v in values:
        product *= 1 + v
    return product - 1


def is_blank(v) -> bool:
    """True for None, empty/whitespace strings, and NaN. Streamlit's data_editor
    (and plain pandas) silently turns an untouched blank cell in a numeric column
    into NaN -- not None -- as soon as ANY other cell in that column has a real
    value, so both need to be treated as "not entered"."""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


