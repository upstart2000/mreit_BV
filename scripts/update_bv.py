"""
Upsert book values for a quarter into data/bv_quarterly.csv, then rebuild
data/pbv_daily.csv so the change takes effect immediately. Used by the app's
"Update Book Values" section, but also callable standalone:

    python update_bv.py "Q3'26" AGNC=8.50 CIM=21.90 MFA=13.10

Once a quarter's book value is saved here, the existing lagged-BV convention
in build_pbv.py picks it up automatically: e.g. saving Q3'26 makes it the
divisor for every daily price in Q4'26 (and for "live" P/BV until Q4'26's own
BV is entered), with no other changes needed.
"""
import sys

import pandas as pd

from build_pbv import build_pbv
from common import BV_QUARTERLY_CSV, is_blank, quarter_end_date


def upsert_book_values(quarter: str, values: dict) -> list:
    """Insert/overwrite (ticker, quarter) -> book_value rows for `quarter`.
    `values` maps ticker -> book_value; blank entries (see `common.is_blank`)
    are skipped. Only the tickers actually supplied are touched -- any other
    ticker already saved for this same quarter (e.g. reported on an earlier
    day) is left alone, so you can update one mREIT at a time as each reports
    earnings, across as many separate saves as you need.
    Returns the list of tickers actually written."""
    quarter_end = quarter_end_date(quarter)  # raises if the label is malformed

    if BV_QUARTERLY_CSV.exists():
        bv = pd.read_csv(BV_QUARTERLY_CSV)
    else:
        bv = pd.DataFrame(columns=["ticker", "quarter", "quarter_end", "book_value"])

    clean = {t: float(v) for t, v in values.items() if not is_blank(v)}
    if not clean:
        return []

    # Replace only the (ticker, quarter) rows we're about to write.
    being_replaced = (bv["quarter"] == quarter) & (bv["ticker"].isin(clean))
    bv = bv[~being_replaced]
    new_rows = pd.DataFrame(
        [{"ticker": t, "quarter": quarter, "quarter_end": quarter_end, "book_value": v} for t, v in clean.items()]
    )
    bv = pd.concat([bv, new_rows], ignore_index=True)
    bv.to_csv(BV_QUARTERLY_CSV, index=False)
    return list(clean.keys())


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    quarter = sys.argv[1]
    values = dict(pair.split("=") for pair in sys.argv[2:])
    written = upsert_book_values(quarter, values)
    print(f"Saved {len(written)} book value(s) for {quarter}: {', '.join(written)}")
    out = build_pbv()
    print(f"Rebuilt {len(out)} daily P/BV rows.")


if __name__ == "__main__":
    main()
