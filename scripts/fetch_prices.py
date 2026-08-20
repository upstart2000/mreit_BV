"""
Fetch daily historical closing prices for all mREIT tickers from yfinance and
cache them locally at data/prices_daily.csv.

Incremental: if the cache already exists, only fetches data from the day after
the latest cached date through today, then appends. Pass --full to wipe and
re-download everything from scratch.

Run this periodically (e.g. after quarter-end) to refresh the local cache.
"""
import argparse
import sys
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from common import BV_QUARTERLY_CSV, PRICES_DAILY_CSV

START_DATE = "2021-01-01"  # comfortably before the earliest BV quarter (Q2'21)


def get_tickers() -> list[str]:
    bv = pd.read_csv(BV_QUARTERLY_CSV)
    return sorted(bv["ticker"].unique().tolist())


def fetch_range(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    print(f"Fetching {len(tickers)} tickers from {start} to {end}...")
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
    )
    if raw.empty:
        return pd.DataFrame(columns=["ticker", "date", "close"])

    frames = []
    for t in tickers:
        try:
            sub = raw[t][["Close"]].dropna()
        except KeyError:
            print(f"  WARNING: no data returned for {t}", file=sys.stderr)
            continue
        sub = sub.reset_index().rename(columns={"Date": "date", "Close": "close"})
        sub["ticker"] = t
        frames.append(sub[["ticker", "date", "close"]])

    if not frames:
        return pd.DataFrame(columns=["ticker", "date", "close"])
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Re-download the full history instead of incrementally updating")
    args = parser.parse_args()

    tickers = get_tickers()
    today = date.today().isoformat()

    if PRICES_DAILY_CSV.exists() and not args.full:
        existing = pd.read_csv(PRICES_DAILY_CSV)
        last_date = existing["date"].max()
        start = (pd.to_datetime(last_date) + timedelta(days=1)).date().isoformat()
        if start > today:
            print(f"Cache already up to date (latest date: {last_date}). Nothing to fetch.")
            return
        new = fetch_range(tickers, start, today)
        if new.empty:
            print("No new data returned (markets may be closed since last fetch).")
            return
        combined = pd.concat([existing, new], ignore_index=True)
        combined = combined.drop_duplicates(subset=["ticker", "date"], keep="last")
    else:
        combined = fetch_range(tickers, START_DATE, today)

    combined = combined.sort_values(["ticker", "date"])
    combined.to_csv(PRICES_DAILY_CSV, index=False)
    print(f"Saved {len(combined)} rows ({combined['ticker'].nunique()} tickers) to {PRICES_DAILY_CSV}")
    print(f"Date range: {combined['date'].min()} to {combined['date'].max()}")


if __name__ == "__main__":
    main()
