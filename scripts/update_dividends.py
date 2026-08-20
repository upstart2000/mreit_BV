"""
Upsert a mREIT's current quarterly dividend per share into data/dividends.csv.
Used by the Rankings tab's editable Dividend column, but also callable standalone:

    python update_dividends.py ADAM=0.30 CIM=0.05

There's no quarter dimension here (unlike book values) -- just each ticker's
CURRENT dividend rate, which stays in effect for Div Yield calculations until
you update it again the next time that mREIT changes its dividend.
"""
import sys

import pandas as pd

from common import DIVIDENDS_CSV, is_blank


def upsert_dividends(values: dict) -> int:
    """Insert/overwrite ticker -> quarterly_dividend rows. `values` maps
    ticker -> quarterly dividend per share; blank entries (see
    `common.is_blank`) are skipped, so a partially-edited table only updates
    the tickers you actually changed. Returns the number of rows written."""
    if DIVIDENDS_CSV.exists():
        div = pd.read_csv(DIVIDENDS_CSV)
    else:
        div = pd.DataFrame(columns=["ticker", "quarterly_dividend"])

    clean = {t: float(v) for t, v in values.items() if not is_blank(v)}
    if not clean:
        return 0

    div = div[~div["ticker"].isin(clean)]
    new_rows = pd.DataFrame([{"ticker": t, "quarterly_dividend": v} for t, v in clean.items()])
    div = pd.concat([div, new_rows], ignore_index=True).sort_values("ticker")
    div.to_csv(DIVIDENDS_CSV, index=False)
    return len(new_rows)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    values = dict(pair.split("=") for pair in sys.argv[1:])
    n = upsert_dividends(values)
    print(f"Saved {n} dividend value(s).")


if __name__ == "__main__":
    main()
