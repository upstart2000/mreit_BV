"""
Combine cached daily prices (data/prices_daily.csv) with quarterly book values
(data/bv_quarterly.csv) into a DAILY Price/Book-Value series, saved to
data/pbv_daily.csv.

Convention (lagged book value): every daily price is divided by the book value
of the PRIOR completed quarter -- since a mREIT's book value for the quarter
currently underway isn't published until after that quarter closes. E.g. all
daily prices falling in Q1'26 (2026-01-01 through 2026-03-31) are divided by
the Q4'25 book value; all daily prices in a quarter whose own BV hasn't been
reported yet are divided by whatever the latest known quarter's BV is. This
mirrors the workbook's own "P/Q2'26 BV" column.

The set of known quarters is read straight from data/bv_quarterly.csv, NOT
hardcoded -- so once a new quarter's book value is added (see update_bv.py /
the app's "Update Book Values" section), re-running this script immediately
starts using it as the divisor for the following quarter's prices, with no
code changes needed.

Output columns:
    ticker, date, price, quarter, bv_quarter, book_value, pbv
where `quarter` is the calendar quarter the price date falls in, and
`bv_quarter` is the prior quarter whose book value was used.
"""
import numpy as np
import pandas as pd

from common import (
    BV_QUARTERLY_CSV,
    PBV_DAILY_CSV,
    PRICES_DAILY_CSV,
    next_quarter_label,
    quarter_end_date,
    sorted_quarters,
)


def build_pbv() -> pd.DataFrame:
    bv = pd.read_csv(BV_QUARTERLY_CSV)
    bv["book_value"] = bv["book_value"].astype(float)
    bv_lookup = {(r.ticker, r.quarter): r.book_value for r in bv.itertuples()}

    known_quarters = sorted_quarters(bv["quarter"].unique())
    n = len(known_quarters)

    prices = pd.read_csv(PRICES_DAILY_CSV)
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.rename(columns={"close": "price"})

    q_ends = pd.to_datetime([quarter_end_date(q) for q in known_quarters]).values

    # For each price date, find the index of the first quarter-end >= that date --
    # that's the calendar quarter the date falls into ("current quarter").
    idx = np.searchsorted(q_ends, prices["date"].values, side="left")

    # The book value used is always from the quarter BEFORE the current one.
    prior_idx = idx - 1
    valid = prior_idx >= 0
    prices = prices.loc[valid].copy()
    prior_idx = prior_idx[valid]
    idx = idx[valid]

    prices["bv_quarter"] = np.array(known_quarters)[prior_idx]
    prices["quarter"] = [
        known_quarters[i] if i < n else next_quarter_label(known_quarters[-1]) for i in idx
    ]

    prices["book_value"] = [
        bv_lookup.get((t, q)) for t, q in zip(prices["ticker"], prices["bv_quarter"])
    ]
    prices = prices.dropna(subset=["book_value"])

    prices["pbv"] = (prices["price"] / prices["book_value"]).round(6)
    prices["price"] = prices["price"].round(4)
    prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")

    out = prices[["ticker", "date", "price", "quarter", "bv_quarter", "book_value", "pbv"]]
    out = out.sort_values(["ticker", "date"])
    out.to_csv(PBV_DAILY_CSV, index=False)
    return out


def main():
    out = build_pbv()
    print(f"Saved {len(out)} daily P/BV rows for {out['ticker'].nunique()} tickers to {PBV_DAILY_CSV}")
    print(f"Date range: {out['date'].min()} to {out['date'].max()}")


if __name__ == "__main__":
    main()
