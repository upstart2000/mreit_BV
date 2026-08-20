# mREITs Price/Book Value

## Setup
```
pip install -r requirements.txt
```

## Deploying (e.g. Streamlit Community Cloud)
`data/prices_daily.csv` and `data/pbv_daily.csv` ARE committed to git, even
though they're regenerable yfinance-derived caches — so a fresh clone/deploy
starts from a recent baseline instead of empty. On every startup, `app.py`
does a fast incremental top-up (`ensure_prices_current()`, rate-limited to
once per 6h *across all sessions* on that server process via
`@st.cache_data(ttl="6h")`, so it can't turn into a yfinance call on every
page interaction) and only falls back to a full 5-year re-fetch
(`bootstrap_data_if_needed()`) if a CSV is genuinely missing, e.g. before the
first commit ever happened. Point a Streamlit Cloud app at this repo with
`app.py` as the entrypoint and it just works. Since the app's own writes to
these CSVs (whether local or on a hosted deploy) don't get pushed back to
GitHub automatically, the *committed* baseline still drifts stale between
runs of the pipeline below (or a manual `git add data/*.csv && git commit`)
— that's fine, it just means each fresh cold start has a few more days to
catch up incrementally, not that anything breaks.

## Data pipeline (run in order, from `scripts/`)
1. `python extract_bv.py` — parses `BV Historical Data.xlsx` → `data/bv_quarterly.csv`
   (book value per share, by ticker/quarter). Re-run whenever the workbook is updated.
2. `python fetch_prices.py --full` — downloads full daily price history for all
   tickers in the workbook from yfinance → `data/prices_daily.csv`. After the first
   run, `python fetch_prices.py` (no `--full`) does an incremental top-up instead of
   re-downloading everything.
3. `python build_pbv.py` — combines the two into `data/pbv_daily.csv`, one
   P/BV multiple for every daily closing price.
4. `python extract_ecn_return.py` — parses the workbook's quarterly
   economic-return columns → `data/ecn_return_quarterly.csv`. Trailing
   1/2/3/4-year figures aren't stored separately; the app computes them on
   the fly (see the caveat below).
5. `python extract_dividends.py` — seeds each mREIT's current quarterly
   dividend per share → `data/dividends.csv`. Safe to re-run: it only adds
   tickers missing from the file, never overwrites one already there, so it
   can't clobber a dividend you've since updated by hand.

**P/BV convention (lagged book value):** every daily price is divided by the
book value of the PRIOR completed quarter — since a mREIT's own book value
for the quarter currently underway isn't published until after that quarter
closes. E.g. every daily price falling in Q1'26 (2026-01-01 through
2026-03-31) is divided by the Q4'25 book value; daily prices in Q3'26
(in progress) are divided by Q2'26, the latest known book value. This matches
the workbook's existing `P/Q2'26 BV` column.

**Economic return convention:** trailing 1/2/3/4-year returns compound the
last (years × 4) quarterly returns, INCLUDING the latest quarter, computed
per ticker as of that ticker's own latest reported quarter (staggered
reporting handled the same way as book values). Note the workbook's own
2/3/4-Year Ecn Return columns actually exclude the latest quarter (confirmed
cell-by-cell against its formulas) while its 1-Year column includes it — an
inconsistency in the source data. `common.trailing_return()` applies the
1-Year convention (window ends at, and includes, the latest quarter)
uniformly across all four horizons, so its 2/3/4-year values will differ
from what's in the workbook.

New quarters don't have to come from the workbook, either: saving a quarter's
book value in the "Update Book Values" tab automatically computes AND SAVES
that quarter's economic return too, as
`(new BV + current dividend) / prior quarter's BV - 1` (see
`scripts/update_ecn_return.py`) — using each ticker's current dividend on
file (`data/dividends.csv`). So the intended flow when a mREIT reports a new
quarter is: update its dividend on the Rankings tab first if it changed,
*then* enter the new book value — both land together automatically.

**Dividend / yield convention:** each mREIT has a single current *quarterly*
dividend per share (`data/dividends.csv`), annualized (× 4) for yield. Div
Yield (Price) = annual dividend ÷ that row's price; Div Yield (Book) = annual
dividend ÷ that row's book value — both reusing the exact price/book value
already shown for the row (live quote or cached close; latest known BV),
so they're always consistent with the P/BV column next to them. The
workbook's own "Div Yield on Book" column references a stale two-quarters-back
book value (confirmed against its formula, and confirmed with the user to be
a bug in the sheet, not intentional) -- this app always uses the latest known
book value instead, so the numbers will differ from the workbook.

## App
From the project root:
```
streamlit run app.py
```
Four tabs:
- **📈 Chart** — select mREITs to plot their historical daily P/BV (MFA is
  selected by default). **🔄 Refresh current price** fetches a live/intraday
  quote and folds it into the line as one more point (live price ÷ latest
  known quarterly book value) — not written back to the CSV cache, just for
  viewing.
- **📊 Rankings** — every mREIT's P/BV and Div Yield (Price / Book) in one
  table, sorted by P/BV, lowest to highest. Shows the latest cached daily
  close until you click **🔄 Refresh live prices**, which fetches a live quote
  for all tickers and recomputes the table from those. The Qtrly Dividend
  column is editable — change it whenever a mREIT announces a new dividend
  (e.g. a raise or cut) and click **💾 Save dividend changes**; only the rows
  you actually changed are written. Also usable from the command line:
  `python scripts/update_dividends.py ADAM=0.32`
- **💹 Economic Returns** — every mREIT's latest-quarter and trailing
  1/2/3/4-year economic return in one table (sorted by latest-quarter return,
  highest first by default; click any column header to re-sort). The
  2/3/4-Year columns are TOTAL (compounded) returns over that period, not
  annualized.
- **📝 Update Book Values** — enter a new quarter's book values once a mREIT
  reports them (e.g. Q3'26 after quarter-end 9/30/26). It defaults to the
  next quarter after the latest one on file, shows the prior quarter's
  values alongside for reference, and on save immediately rebuilds
  `data/pbv_daily.csv`. No code changes needed — the lagged-BV convention
  picks up the new quarter automatically as the divisor for the *following*
  quarter's prices (saving Q3'26 starts applying to Q4'26 once its price data
  exists, and the field's default will then advance to Q4'26 on its own),
  and as the divisor for the live refresh until a newer quarter is entered.
  It also auto-computes that quarter's economic return for every ticker saved
  (see above) and reports which tickers it could/couldn't compute for. You
  can also do this from the command line:
  `python scripts/update_bv.py "Q3'26" AGNC=8.50 MFA=13.10 ...`

## Files
- `BV Historical Data.xlsx` — source workbook (book value + economic return by quarter, per ticker).
- `scripts/common.py` — shared constants/helpers: ticker list, quarter-label ↔ quarter-end date
  conversion, known stock splits, file paths.
- `scripts/extract_bv.py`, `fetch_prices.py`, `build_pbv.py`, `extract_ecn_return.py`, `extract_dividends.py` — the pipeline above.
  Re-running `extract_bv.py` preserves any quarters added later via `update_bv.py`
  (it only overwrites the fixed set of quarters that come from the workbook).
- `scripts/update_bv.py` — upserts a quarter's book values and rebuilds `pbv_daily.csv`;
  backs the app's "Update Book Values" section and is also usable standalone.
- `scripts/update_dividends.py` — upserts a ticker's current quarterly dividend;
  backs the Rankings tab's editable Dividend column and is also usable standalone.
- `scripts/update_ecn_return.py` — computes and saves a quarter's economic return
  from book values + current dividend; called automatically after saving book
  values, and also usable standalone: `python update_ecn_return.py "Q3'26" ADAM AGNC`.
- `data/bv_quarterly.csv`, `data/prices_daily.csv`, `data/pbv_daily.csv` — cached P/BV data.
- `data/ecn_return_quarterly.csv` — cached quarterly economic returns (trailing figures computed on the fly).
- `data/dividends.csv` — each ticker's current quarterly dividend per share.
- `app.py` — Streamlit viewer.
