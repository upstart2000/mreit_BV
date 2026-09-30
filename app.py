"""
Streamlit app: plot historical Price/Book-Value multiples for selected mREITs.

Run with:
    streamlit run app.py

Data comes from local CSV caches built by the scripts/ pipeline:
    scripts/extract_bv.py   -> data/bv_quarterly.csv  (book values, from the xlsx)
    scripts/fetch_prices.py -> data/prices_daily.csv  (daily closes, from yfinance)
    scripts/build_pbv.py    -> data/pbv_daily.csv      (daily P/BV, lagged BV)
All of the above ARE committed to git (a recent baseline, refreshed as the app
runs) so a fresh clone/deploy starts warm. On startup, ensure_prices_current()
does a fast incremental top-up (rate-limited to once per 6h across all
sessions) and bootstrap_data_if_needed() falls back to building anything
that's genuinely missing from scratch -- see their docstrings below.

Tabs:
    Chart              - historical daily P/BV for tickers you select, with a
                          "Refresh current price" button that folds a live
                          intraday quote into the line as one more point.
    Rankings           - all mREITs' P/BV in one table, lowest to highest;
                          "Refresh live prices" re-fetches quotes for everyone.
                          Also where you enter your own interim book value
                          estimates (data/bv_estimates.csv) to see implied
                          P/BV and yields before a mREIT reports.
    Economic Returns   - latest-quarter and trailing 1/2/3/4-year economic
                          return for all mREITs, from scripts/extract_ecn_return.py.
    Update Book Values - enter a new quarter's book values once a mREIT
                          reports them; rebuilds pbv_daily.csv immediately.
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.colors as pcolors
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

PALETTE = pcolors.qualitative.Plotly

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from build_pbv import build_pbv  # noqa: E402
from common import (  # noqa: E402
    BV_ESTIMATES_CSV,
    BV_QUARTERLY_CSV,
    DIVIDENDS_CSV,
    ECN_RETURN_QUARTERLY_CSV,
    PBV_DAILY_CSV,
    PRICES_DAILY_CSV,
    next_quarter_label,
    quarter_end_date,
    sorted_quarters,
    trailing_return,
)
from extract_bv import extract_bv  # noqa: E402
from extract_dividends import extract_dividends  # noqa: E402
from extract_ecn_return import extract_ecn_return  # noqa: E402
from fetch_prices import fetch_prices  # noqa: E402
from update_bv import upsert_book_values  # noqa: E402
from update_bv_estimates import clear_bv_estimates, upsert_bv_estimates  # noqa: E402
from update_ecn_return import auto_compute_ecn_returns  # noqa: E402
from update_dividends import upsert_dividends  # noqa: E402

st.set_page_config(page_title="mREIT P/BV Multiples", layout="wide")

DEFAULT_TICKER = "MFA"


@st.cache_data
def load_pbv() -> pd.DataFrame:
    df = pd.read_csv(PBV_DAILY_CSV)
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data
def load_bv() -> pd.DataFrame:
    return pd.read_csv(BV_QUARTERLY_CSV)


@st.cache_data
def load_ecn_return_quarterly() -> pd.DataFrame:
    df = pd.read_csv(ECN_RETURN_QUARTERLY_CSV)
    df["quarter_end"] = pd.to_datetime(df["quarter_end"])
    return df


@st.cache_data
def load_dividends() -> dict:
    if not DIVIDENDS_CSV.exists():
        return {}
    df = pd.read_csv(DIVIDENDS_CSV)
    return dict(zip(df["ticker"], df["quarterly_dividend"]))


@st.cache_data
def load_bv_estimates() -> dict:
    """{ticker: (est_book_value, updated_date_str)} -- your own interim book
    value estimates, used only for what-if P/BV and yields (never for the
    daily P/BV history or economic returns)."""
    if not BV_ESTIMATES_CSV.exists():
        return {}
    df = pd.read_csv(BV_ESTIMATES_CSV)
    return {r.ticker: (float(r.est_book_value), str(r.updated)) for r in df.itertuples()}


def latest_bv_snapshot(bv: pd.DataFrame):
    """(latest known quarter label, {ticker: book_value}) as of that quarter."""
    latest_quarter = sorted_quarters(bv["quarter"].unique())[-1]
    latest = bv[bv["quarter"] == latest_quarter]
    return latest_quarter, dict(zip(latest["ticker"], latest["book_value"]))


def fetch_live_prices(tickers: list[str]) -> dict:
    """Best-effort live/intraday last price per ticker via yfinance."""
    prices = {}
    for t in tickers:
        try:
            price = yf.Ticker(t).fast_info.last_price  # fast_info.get("last_price") mis-keys (it's "lastPrice"); use the attribute
            if price:
                prices[t] = float(price)
        except Exception:
            continue
    return prices


def refresh_live_prices(tickers: list[str]):
    """Fetch live quotes for `tickers` and merge them into session state, shared
    across tabs, so refreshing on one tab doesn't drop quotes fetched on another."""
    new_prices = fetch_live_prices(tickers)
    live = st.session_state.get("live_prices", {})
    live.update(new_prices)
    st.session_state["live_prices"] = live
    st.session_state["live_ts"] = datetime.now()


@st.cache_data(ttl="6h")
def ensure_prices_current():
    """Incrementally top up data/prices_daily.csv (and rebuild pbv_daily.csv if
    that added anything), at most once per TTL window -- shared across every
    session on this server process, so it can't turn into a yfinance call on
    every page interaction. Both CSVs are committed to git with a recent
    baseline specifically so this only ever has a few days to catch up on a
    fresh clone/deploy, instead of re-fetching 5 years of history every time."""
    new_data = fetch_prices(full=False)
    if new_data is not None:
        build_pbv()
    return True


def bootstrap_data_if_needed():
    """First-run setup for a fresh clone/deploy (e.g. Streamlit Community Cloud
    pulling straight from GitHub). Everything here is normally already
    committed and present -- this is a fallback for the (rare) case one of
    them is genuinely missing, e.g. before the very first commit."""
    if not BV_QUARTERLY_CSV.exists():
        with st.spinner("First-time setup: extracting book values from the workbook..."):
            extract_bv()
    if not DIVIDENDS_CSV.exists():
        with st.spinner("First-time setup: extracting dividends from the workbook..."):
            extract_dividends()
    if not ECN_RETURN_QUARTERLY_CSV.exists():
        with st.spinner("First-time setup: extracting economic returns from the workbook..."):
            extract_ecn_return()
    if not PRICES_DAILY_CSV.exists():
        with st.spinner(
            "First-time setup: fetching full price history from Yahoo Finance "
            "(only needed once ever -- after this, a committed baseline in git "
            "keeps future cold starts fast)..."
        ):
            fetch_prices(full=True)
    else:
        with st.spinner("Checking for newer prices..."):
            ensure_prices_current()
    if not PBV_DAILY_CSV.exists():
        with st.spinner("First-time setup: computing P/BV..."):
            build_pbv()


bootstrap_data_if_needed()

if not PBV_DAILY_CSV.exists():
    st.error(
        "Still couldn't find/build P/BV data after first-run setup -- see the "
        "app logs for what failed. You can also run the pipeline manually:\n\n"
        "    cd scripts\n    python extract_bv.py\n    python fetch_prices.py --full\n    python build_pbv.py"
    )
    st.stop()

pbv_df = load_pbv()
bv_df = load_bv()
latest_bv_quarter, latest_bv = latest_bv_snapshot(bv_df)
bv_estimates = load_bv_estimates()
all_tickers = sorted(pbv_df["ticker"].unique())

st.markdown("## mREIT Price / Book Value Multiples")

tab_chart, tab_rankings, tab_ecn_return, tab_update = st.tabs(
    ["📈 Chart", "📊 Rankings", "💹 Economic Returns", "📝 Update Book Values"]
)

# ----------------------------------------------------------------------------
# Chart tab
# ----------------------------------------------------------------------------
with tab_chart:
    sel_col, btn_col = st.columns([4, 1], vertical_alignment="bottom")
    with sel_col:
        default_selection = [DEFAULT_TICKER] if DEFAULT_TICKER in all_tickers else all_tickers[:1]
        selected = st.multiselect("mREITs", options=all_tickers, default=default_selection)
    with btn_col:
        refresh_clicked = st.button("🔄 Refresh current price", use_container_width=True)
    st.caption(
        f"Refresh fetches a live quote and divides by the latest known book value "
        f"({latest_bv_quarter}) to show where each REIT trades right now -- or by "
        f"your own estimate, for tickers you've entered one for on the Rankings tab."
    )

    if not selected:
        st.info("Select one or more mREITs above to plot.")
    else:
        if refresh_clicked:
            with st.spinner("Fetching live prices..."):
                refresh_live_prices(selected)

        live_prices = st.session_state.get("live_prices", {})
        live_ts = st.session_state.get("live_ts")

        fig = go.Figure()
        for i, ticker in enumerate(selected):
            color = PALETTE[i % len(PALETTE)]
            tdf = pbv_df[pbv_df["ticker"] == ticker].sort_values("date")
            x = list(tdf["date"])
            y = list(tdf["pbv"])
            hover_labels = list(tdf["quarter"])

            # Fold today's live quote straight into the same line as one more point,
            # so it reads as a continuation of the series rather than a separate overlay.
            # If you've entered your own interim BV estimate for this ticker (Rankings
            # tab), the live point uses it instead, and says so in the hover label.
            live_bv = bv_estimates[ticker][0] if ticker in bv_estimates else latest_bv.get(ticker)
            if ticker in live_prices and live_bv and x:
                live_pbv = live_prices[ticker] / live_bv
                ts_label = live_ts.strftime("%Y-%m-%d %H:%M") if live_ts else "now"
                x.append(pd.Timestamp.now())
                y.append(live_pbv)
                est_note = " (est. BV)" if ticker in bv_estimates else ""
                hover_labels.append(f"Live @ {ts_label}{est_note}")

            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=y,
                    mode="lines",
                    name=ticker,
                    line=dict(color=color),
                    customdata=hover_labels,
                    hovertemplate="%{customdata}<br>P/BV: %{y:.2f}<extra>" + ticker + "</extra>",
                )
            )

            # Dashed reference line at this ticker's most recent P/BV, spanning the full window
            if y:
                fig.add_hline(
                    y=y[-1],
                    line_dash="dash",
                    line_color=color,
                    opacity=0.6,
                    annotation_text=f"{ticker} {y[-1]:.2f}x",
                    annotation_position="right",
                    annotation_font_color=color,
                )

        fig.update_layout(
            height=600,
            xaxis_title="Date",
            yaxis_title="Price / Book Value",
            hovermode="x unified",
            legend_title="Ticker",
            showlegend=True,  # Plotly hides the legend by default with only one trace
            dragmode="zoom",
        )
        # Range slider below the chart: drag its handles to pick a date window. Unlike
        # dragging a zoom box on the chart itself (which clips the y-axis to wherever
        # your mouse happened to be vertically), the range slider only ever selects an
        # x-range -- Plotly then auto-fits the y-axis to whatever's actually visible.
        fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.08))
        fig.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5)

        st.plotly_chart(
            fig,
            use_container_width=True,
            config={
                "scrollZoom": True,
                "displayModeBar": True,  # always visible (default is hover-only), so the reset icon is easy to find
                "modeBarButtonsToRemove": ["select2d", "lasso2d"],  # not useful on a time series
            },
        )
        st.caption(
            "🔍 Drag the slider below the chart to pick a date range (the y-axis auto-fits "
            "to what's visible). You can also drag directly on the chart to zoom, or scroll "
            "to zoom -- to reset, double-click the chart or click the 🏠 icon in the toolbar."
        )

        if live_prices:
            shown_live = {t: p for t, p in live_prices.items() if t in selected}
            if shown_live:
                st.subheader(f"Live snapshot ({live_ts.strftime('%Y-%m-%d %H:%M:%S')})")
                live_rows = []
                for t in selected:
                    if t not in shown_live:
                        continue
                    row = {
                        "ticker": t,
                        "live_price": shown_live[t],
                        f"{latest_bv_quarter}_book_value": latest_bv.get(t),
                        "live_pbv": shown_live[t] / latest_bv[t] if t in latest_bv else None,
                    }
                    if any(s in bv_estimates for s in shown_live):
                        est_bv = bv_estimates[t][0] if t in bv_estimates else None
                        row["est_book_value"] = est_bv
                        row["live_pbv_est"] = shown_live[t] / est_bv if est_bv else None
                    live_rows.append(row)
                st.dataframe(pd.DataFrame(live_rows), use_container_width=True, hide_index=True)

        with st.expander("Underlying daily data"):
            st.dataframe(
                pbv_df[pbv_df["ticker"].isin(selected)].sort_values(["ticker", "date"], ascending=[True, False]),
                use_container_width=True,
                hide_index=True,
            )

# ----------------------------------------------------------------------------
# Rankings tab
# ----------------------------------------------------------------------------
with tab_rankings:
    st.caption(
        "All mREITs' P/BV, lowest to highest. Shows the latest cached daily close "
        "until you refresh; refreshing fetches a live quote for every ticker. "
        "Div Yield uses that same price/book value, annualizing the quarterly "
        "dividend below (× 4) -- edit a ticker's dividend whenever it changes "
        "(e.g. a mREIT announces a raise or cut) and save to update the yields."
    )
    st.caption(
        "✏️ **Est. BV**: between earnings reports, type your own estimate of a "
        "ticker's current book value to see the implied P/BV and yields off it -- "
        "those rows show BV Quarter as *Est.*, and P/BV (Reported) keeps the "
        "reported-BV multiple for comparison. Estimates are saved separately and "
        "never touch the chart history or economic returns. Clear the cell to "
        "drop one; saving the real book value in Update Book Values clears it "
        "automatically."
    )
    refresh_all_clicked = st.button("🔄 Refresh live prices", key="refresh_all_prices")
    if refresh_all_clicked:
        with st.spinner("Fetching live prices for all mREITs..."):
            refresh_live_prices(all_tickers)

    live_prices = st.session_state.get("live_prices", {})
    live_ts = st.session_state.get("live_ts")
    latest_daily = pbv_df.sort_values("date").groupby("ticker").tail(1).set_index("ticker")
    dividends = load_dividends()

    # Note: not every ticker necessarily has book value for latest_bv_quarter yet
    # (mREITs report on staggered dates) -- for those we fall back to their own
    # latest cached daily row, which already carries the correct bv_quarter it
    # actually used, so the table never mislabels a stale book value as current.
    rows = []
    for t in all_tickers:
        bv = latest_bv.get(t)
        if t in live_prices and bv:
            price = live_prices[t]
            pbv = price / bv
            as_of = live_ts.strftime("%Y-%m-%d %H:%M") if live_ts else "live"
            source = "live"
            bv_quarter_used = latest_bv_quarter
        elif t in latest_daily.index:
            price = latest_daily.loc[t, "price"]
            pbv = latest_daily.loc[t, "pbv"]
            bv = latest_daily.loc[t, "book_value"]
            as_of = latest_daily.loc[t, "date"].strftime("%Y-%m-%d")
            source = "cached close"
            bv_quarter_used = latest_daily.loc[t, "bv_quarter"]
        else:
            continue

        # Your own interim estimate, if entered, overrides the reported BV for
        # this row's P/BV and yields; the reported-BV multiple is kept alongside.
        pbv_reported = pbv
        est = bv_estimates.get(t)
        if est:
            bv = est[0]
            pbv = price / bv
            est_date = pd.Timestamp(est[1])
            bv_quarter_used = f"Est. {est_date.month}/{est_date.day}"

        quarterly_dividend = dividends.get(t)
        annual_dividend = quarterly_dividend * 4 if quarterly_dividend is not None else None
        rows.append(
            {
                "ticker": t,
                "pbv": round(pbv, 3),
                "pbv_reported": round(pbv_reported, 3),
                "div_yield_price": annual_dividend / price if annual_dividend else None,
                "div_yield_book": annual_dividend / bv if annual_dividend else None,
                "quarterly_dividend": quarterly_dividend,
                "price": round(price, 2),
                "book_value": bv,
                "est_book_value": est[0] if est else None,
                "bv_quarter": bv_quarter_used,
                "as_of": as_of,
                "source": source,
            }
        )

    table = pd.DataFrame(rows).sort_values("pbv").reset_index(drop=True)
    # All-blank on a fresh start would otherwise be an object column, which the
    # editor won't treat as numeric.
    table["est_book_value"] = table["est_book_value"].astype(float)
    edited = st.data_editor(
        table,
        use_container_width=True,
        hide_index=True,
        disabled=[c for c in table.columns if c not in ("quarterly_dividend", "est_book_value")],
        column_config={
            "pbv": st.column_config.NumberColumn("P/BV", format="%.2fx"),
            "pbv_reported": st.column_config.NumberColumn("P/BV (Reported)", format="%.2fx"),
            "div_yield_price": st.column_config.NumberColumn("Div Yield (Price)", format="percent"),
            "div_yield_book": st.column_config.NumberColumn("Div Yield (Book)", format="percent"),
            "quarterly_dividend": st.column_config.NumberColumn(
                "Qtrly Dividend", min_value=0.0, step=0.01, format="%.2f"
            ),
            "price": st.column_config.NumberColumn("Price"),
            "book_value": st.column_config.NumberColumn("Book Value"),
            "est_book_value": st.column_config.NumberColumn(
                "✏️ Est. BV", min_value=0.0, step=0.01, format="%.2f"
            ),
            "bv_quarter": st.column_config.TextColumn("BV Quarter"),
        },
        key="rankings_editor",
    )

    if st.button("💾 Save dividend / estimate changes", key="save_dividends"):
        changed = {}
        for t, old, new in zip(table["ticker"], table["quarterly_dividend"], edited["quarterly_dividend"]):
            if pd.isna(new):
                continue
            if pd.isna(old) or abs(float(new) - float(old)) > 1e-9:
                changed[t] = float(new)
        n = upsert_dividends(changed)
        # Every row's estimate is passed through; upsert_bv_estimates only writes
        # the ones that actually changed, and a now-blank cell clears that estimate.
        est_set, est_cleared = upsert_bv_estimates(dict(zip(edited["ticker"], edited["est_book_value"])))
        if n == 0 and not est_set and not est_cleared:
            st.warning("No dividend or estimate changes to save.")
        else:
            load_dividends.clear()
            load_bv_estimates.clear()
            st.rerun()

# ----------------------------------------------------------------------------
# Economic Returns tab
# ----------------------------------------------------------------------------
with tab_ecn_return:
    ecn_quarterly = load_ecn_return_quarterly()

    st.caption(
        "Latest-quarter and trailing economic return per mREIT, each as of that "
        "ticker's own latest reported quarter -- click any column header to re-sort."
    )
    st.caption(
        "Note: the 2/3/4-Year columns are TOTAL returns over that period "
        "(compounded, not annualized) -- e.g. the 4-Year figure is the full "
        "cumulative return across 4 years, not a per-year rate."
    )

    known_quarters = ecn_quarterly["quarter"].unique()
    latest_qtr = ecn_quarterly.sort_values("quarter_end").groupby("ticker").tail(1).set_index("ticker")

    rows = []
    for t in sorted(ecn_quarterly["ticker"].unique()):
        returns = ecn_quarterly[ecn_quarterly["ticker"] == t].set_index("quarter")["ecn_return"].to_dict()
        as_of = latest_qtr.loc[t, "quarter"]
        row = {
            "ticker": t,
            "latest_quarter": as_of,
            "latest_qtr_return": latest_qtr.loc[t, "ecn_return"],
            "1y": trailing_return(returns, known_quarters, as_of, 1),
            "2y": trailing_return(returns, known_quarters, as_of, 2),
            "3y": trailing_return(returns, known_quarters, as_of, 3),
            "4y": trailing_return(returns, known_quarters, as_of, 4),
        }
        rows.append(row)

    ecn_table = pd.DataFrame(rows).sort_values("latest_qtr_return", ascending=False).reset_index(drop=True)
    st.dataframe(
        ecn_table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "latest_quarter": st.column_config.TextColumn("Latest Qtr"),
            "latest_qtr_return": st.column_config.NumberColumn("Latest Qtr Return", format="percent"),
            "1y": st.column_config.NumberColumn("1-Year", format="percent"),
            "2y": st.column_config.NumberColumn("2-Year", format="percent"),
            "3y": st.column_config.NumberColumn("3-Year", format="percent"),
            "4y": st.column_config.NumberColumn("4-Year", format="percent"),
        },
    )

# ----------------------------------------------------------------------------
# Update Book Values tab
# ----------------------------------------------------------------------------
with tab_update:
    st.caption(f"Latest quarter on file: {latest_bv_quarter}")
    target_quarter = st.text_input(
        "Quarter to enter/update",
        value=next_quarter_label(latest_bv_quarter),
        help="Defaults to the next quarter after the latest one on file. You can "
        "type any other quarter (e.g. to correct a past one) in the same "
        "Qx'yy format.",
    )
    st.caption(
        f"Saving book values for a quarter makes them the divisor for the FOLLOWING "
        f"quarter's daily P/BV (and for the live refresh, until an even newer "
        f"quarter is entered) -- e.g. saving Q3'26 here starts applying to Q4'26 prices. "
        f"It also automatically computes that quarter's economic return -- "
        f"(new BV + current dividend) ÷ prior BV − 1 -- using each ticker's current "
        f"dividend from the Rankings tab, so update the dividend there FIRST if it "
        f"changed (e.g. a mREIT raises or cuts) before saving the new book value here. "
        f"Only enter REPORTED book values here -- for your own interim guesses, use "
        f"the Est. BV column on the Rankings tab instead (saving a ticker's newest "
        f"reported value here clears its estimate)."
    )

    try:
        target_quarter_end = quarter_end_date(target_quarter)
    except ValueError:
        st.error("That doesn't look like a valid quarter label -- use the format Qx'yy, e.g. Q3'26.")
    else:
        existing_for_target = bv_df[bv_df["quarter"] == target_quarter].set_index("ticker")["book_value"]
        prior_quarter_for_target = None
        older = [q for q in sorted_quarters(bv_df["quarter"].unique()) if quarter_end_date(q) < target_quarter_end]
        if older:
            prior_quarter_for_target = older[-1]
        prior_values = (
            bv_df[bv_df["quarter"] == prior_quarter_for_target].set_index("ticker")["book_value"]
            if prior_quarter_for_target
            else pd.Series(dtype=float)
        )

        edit_df = pd.DataFrame(
            {
                "ticker": all_tickers,
                f"{prior_quarter_for_target or 'prior'}_book_value": [
                    prior_values.get(t) for t in all_tickers
                ],
                "new_book_value": [existing_for_target.get(t) for t in all_tickers],
            }
        )
        edited = st.data_editor(
            edit_df,
            use_container_width=True,
            hide_index=True,
            disabled=["ticker", f"{prior_quarter_for_target or 'prior'}_book_value"],
            column_config={
                "new_book_value": st.column_config.NumberColumn(
                    f"{target_quarter} book value", min_value=0.0, step=0.01, format="%.2f"
                )
            },
            key=f"bv_editor_{target_quarter}",
        )

        if st.button("💾 Save book values", type="primary"):
            values = dict(zip(edited["ticker"], edited["new_book_value"]))
            written = upsert_book_values(target_quarter, values)
            if not written:
                st.warning("No values entered -- nothing saved.")
            else:
                build_pbv()
                computed, skipped = auto_compute_ecn_returns(target_quarter, written)
                # A newly reported quarter supersedes any interim estimate for those
                # tickers -- but correcting an older quarter shouldn't wipe them.
                if quarter_end_date(target_quarter) >= quarter_end_date(latest_bv_quarter):
                    clear_bv_estimates(written)
                    load_bv_estimates.clear()
                load_pbv.clear()
                load_bv.clear()
                load_ecn_return_quarterly.clear()
                msg = f"Saved {len(written)} book value(s) for {target_quarter} and refreshed P/BV."
                if computed:
                    msg += f" Also computed {target_quarter} economic return for: {', '.join(computed)}."
                if skipped:
                    details = "; ".join(f"{t} ({reason})" for t, reason in skipped.items())
                    msg += f" Couldn't compute economic return for: {details}."
                st.success(msg)
                st.rerun()
