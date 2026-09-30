"""
Your own interim book value estimates, kept in data/bv_estimates.csv --
completely separate from the reported book values in data/bv_quarterly.csv.

Between earnings reports a mREIT's book value can move a lot, so the Rankings
tab lets you type in your own current estimate per ticker and see the implied
P/BV and dividend yields off it. Estimates are ONLY used for those what-if
numbers: they never feed data/pbv_daily.csv, the chart history, or economic
returns. Saving a ticker's real reported book value in the "Update Book
Values" tab clears that ticker's estimate automatically.

Also callable standalone (a blank value clears that ticker's estimate):

    python update_bv_estimates.py AGNC=8.40 MFA=12.95 CIM=
"""
import sys
from datetime import date

import pandas as pd

from common import BV_ESTIMATES_CSV, is_blank

COLUMNS = ["ticker", "est_book_value", "updated"]


def load_bv_estimates() -> pd.DataFrame:
    if not BV_ESTIMATES_CSV.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(BV_ESTIMATES_CSV)


def upsert_bv_estimates(values: dict) -> tuple:
    """Apply ticker -> estimated book value edits. A number sets/overwrites
    that ticker's estimate (stamped with today's date); a blank (see
    `common.is_blank`) removes it. Returns (set, cleared) ticker lists,
    counting only tickers whose estimate actually changed."""
    est = load_bv_estimates()
    current = dict(zip(est["ticker"], est["est_book_value"]))

    to_set = {}
    to_clear = []
    for t, v in values.items():
        if is_blank(v):
            if t in current:
                to_clear.append(t)
        elif t not in current or abs(float(v) - float(current[t])) > 1e-9:
            to_set[t] = float(v)

    if not to_set and not to_clear:
        return [], []

    est = est[~est["ticker"].isin(list(to_set) + to_clear)]
    today = date.today().isoformat()
    new_rows = pd.DataFrame([{"ticker": t, "est_book_value": v, "updated": today} for t, v in to_set.items()])
    est = pd.concat([est, new_rows], ignore_index=True) if len(new_rows) else est
    est.sort_values("ticker")[COLUMNS].to_csv(BV_ESTIMATES_CSV, index=False)
    return list(to_set), to_clear


def clear_bv_estimates(tickers: list) -> list:
    """Remove any estimates for `tickers` (e.g. once their real book value is
    reported). Returns the tickers that actually had one."""
    _, cleared = upsert_bv_estimates({t: None for t in tickers})
    return cleared


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    values = dict(pair.split("=") for pair in sys.argv[1:])
    set_, cleared = upsert_bv_estimates(values)
    print(f"Set {len(set_)} estimate(s): {', '.join(set_) or '-'}; cleared {len(cleared)}: {', '.join(cleared) or '-'}")


if __name__ == "__main__":
    main()
