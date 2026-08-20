# mREITs Price/Book Value

## Setup
```
pip install -r requirements.txt
```

## Data pipeline (run in order, from `scripts/`)
1. `python extract_bv.py` — parses `BV Historical Data.xlsx` → `data/bv_quarterly.csv`
   (book value per share, by ticker/quarter). Re-run whenever the workbook is updated.
2. `python fetch_prices.py --full` — downloads full daily price history for all
   tickers in the workbook from yfinance → `data/prices_daily.csv`. After the first
   run, `python fetch_prices.py` (no `--full`) does an incremental top-up instead of
   re-downloading everything.
3. `python build_pbv.py` — combines the two into `data/pbv_daily.csv`, one
   P/BV multiple for every daily closing price.

**P/BV convention (lagged book value):** every daily price is divided by the
book value of the PRIOR completed quarter — since a mREIT's own book value
for the quarter currently underway isn't published until after that quarter
closes. E.g. every daily price falling in Q1'26 (2026-01-01 through
2026-03-31) is divided by the Q4'25 book value; daily prices in Q3'26
(in progress) are divided by Q2'26, the latest known book value. This matches
the workbook's existing `P/Q2'26 BV` column.

## App
From the project root:
```
streamlit run app.py
```
Three tabs:
- **📈 Chart** — select mREITs to plot their historical daily P/BV (MFA is
  selected by default). **🔄 Refresh current price** fetches a live/intraday
  quote and folds it into the line as one more point (live price ÷ latest
  known quarterly book value) — not written back to the CSV cache, just for
  viewing.
- **📊 Rankings** — every mREIT's P/BV in one table, lowest to highest.
  Shows the latest cached daily close until you click **🔄 Refresh live
  prices**, which fetches a live quote for all tickers and recomputes the
  table from those.
- **📝 Update Book Values** — enter a new quarter's book values once a mREIT
  reports them (e.g. Q3'26 after quarter-end 9/30/26). It defaults to the
  next quarter after the latest one on file, shows the prior quarter's
  values alongside for reference, and on save immediately rebuilds
  `data/pbv_daily.csv`. No code changes needed — the lagged-BV convention
  picks up the new quarter automatically as the divisor for the *following*
  quarter's prices (saving Q3'26 starts applying to Q4'26 once its price data
  exists, and the field's default will then advance to Q4'26 on its own),
  and as the divisor for the live refresh until a newer quarter is entered.
  You can also do this from the command line:
  `python scripts/update_bv.py "Q3'26" AGNC=8.50 MFA=13.10 ...`

## Files
- `BV Historical Data.xlsx` — source workbook (book value + economic return by quarter, per ticker).
- `scripts/common.py` — shared constants/helpers: ticker list, quarter-label ↔ quarter-end date
  conversion, known stock splits, file paths.
- `scripts/extract_bv.py`, `fetch_prices.py`, `build_pbv.py` — the pipeline above.
  Re-running `extract_bv.py` preserves any quarters added later via `update_bv.py`
  (it only overwrites the fixed set of quarters that come from the workbook).
- `scripts/update_bv.py` — upserts a quarter's book values and rebuilds `pbv_daily.csv`;
  backs the app's "Update Book Values" section and is also usable standalone.
- `data/bv_quarterly.csv`, `data/prices_daily.csv`, `data/pbv_daily.csv` — cached local data.
- `app.py` — Streamlit viewer.
