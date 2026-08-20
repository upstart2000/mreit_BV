"""Shared constants and paths for the mREITs P/BV project."""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

SOURCE_XLSX = PROJECT_ROOT / "BV Historical Data.xlsx"

BV_QUARTERLY_CSV = DATA_DIR / "bv_quarterly.csv"
PRICES_DAILY_CSV = DATA_DIR / "prices_daily.csv"
PBV_DAILY_CSV = DATA_DIR / "pbv_daily.csv"

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
