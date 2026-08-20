"""
Automatically compute and save a quarter's economic return for one or more
tickers, from book values already on file and each ticker's current dividend:

    Ecn Return(Qn) = (BV(Qn) + Dividend) / BV(Q(n-1)) - 1

This is called automatically after saving book values in the app's "Update
Book Values" tab (and by update_bv.py's CLI), so saving Q3'26's book value
for a ticker immediately computes and stores its Q3'26 economic return too --
no separate step needed.

The dividend used is whatever's currently on file in data/dividends.csv, on
the assumption you keep it current (see the Rankings tab's editable Qtrly
Dividend column): update the dividend FIRST if it changed, then enter the new
book value, so both reflect the same quarter. This works well for rolling
forward the latest quarter, but if you're retroactively correcting an OLDER
quarter's book value, the dividend on file may no longer match what was
actually paid back then -- in that case, better to edit
data/ecn_return_quarterly.csv directly (or pass the correct value into
upsert_ecn_returns yourself) rather than relying on the automatic computation.
"""
import sys

import pandas as pd

from common import (
    BV_QUARTERLY_CSV,
    DIVIDENDS_CSV,
    ECN_RETURN_QUARTERLY_CSV,
    is_blank,
    prior_quarter_in,
    quarter_end_date,
    sorted_quarters,
)


def upsert_ecn_returns(quarter: str, values: dict) -> list:
    """Insert/overwrite (ticker, quarter) -> ecn_return rows for `quarter`.
    Same semantics as update_bv.upsert_book_values: blanks are skipped, and
    only the tickers actually supplied are touched. Returns the tickers
    actually written."""
    quarter_end = quarter_end_date(quarter)

    if ECN_RETURN_QUARTERLY_CSV.exists():
        ecn = pd.read_csv(ECN_RETURN_QUARTERLY_CSV)
    else:
        ecn = pd.DataFrame(columns=["ticker", "quarter", "quarter_end", "ecn_return"])

    clean = {t: float(v) for t, v in values.items() if not is_blank(v)}
    if not clean:
        return []

    being_replaced = (ecn["quarter"] == quarter) & (ecn["ticker"].isin(clean))
    ecn = ecn[~being_replaced]
    new_rows = pd.DataFrame(
        [
            {"ticker": t, "quarter": quarter, "quarter_end": quarter_end, "ecn_return": round(v, 6)}
            for t, v in clean.items()
        ]
    )
    ecn = pd.concat([ecn, new_rows], ignore_index=True)
    ecn.to_csv(ECN_RETURN_QUARTERLY_CSV, index=False)
    return list(clean.keys())


def auto_compute_ecn_returns(quarter: str, tickers: list) -> tuple:
    """For each ticker in `tickers`, compute quarter's economic return from
    book values on file and the ticker's current dividend, then save it.

    Returns (computed, skipped): `computed` maps ticker -> the value that was
    saved; `skipped` maps ticker -> a short reason it couldn't be computed
    (no book value for `quarter`, no prior quarter's book value on file for
    that ticker, or no dividend on file)."""
    bv = pd.read_csv(BV_QUARTERLY_CSV)
    if DIVIDENDS_CSV.exists():
        div_df = pd.read_csv(DIVIDENDS_CSV)
        dividends = dict(zip(div_df["ticker"], div_df["quarterly_dividend"]))
    else:
        dividends = {}

    computed = {}
    skipped = {}
    for t in tickers:
        ticker_bv = bv[bv["ticker"] == t].set_index("quarter")["book_value"]
        if quarter not in ticker_bv.index:
            skipped[t] = f"no book value on file for {quarter}"
            continue
        new_bv = ticker_bv[quarter]

        prior_q = prior_quarter_in(sorted_quarters(ticker_bv.index), quarter)
        if prior_q is None:
            skipped[t] = "no prior quarter's book value on file for this ticker"
            continue
        prior_bv = ticker_bv[prior_q]

        dividend = dividends.get(t)
        if dividend is None:
            skipped[t] = "no dividend on file"
            continue

        computed[t] = (new_bv + dividend) / prior_bv - 1

    if computed:
        upsert_ecn_returns(quarter, computed)
    return computed, skipped


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    quarter = sys.argv[1]
    tickers = sys.argv[2:]
    computed, skipped = auto_compute_ecn_returns(quarter, tickers)
    for t, v in computed.items():
        print(f"{t} {quarter} economic return: {v:.4%}")
    for t, reason in skipped.items():
        print(f"{t}: skipped -- {reason}")


if __name__ == "__main__":
    main()
