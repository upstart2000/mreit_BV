"""
Streamlit app: plot historical Price/Book-Value multiples for selected mREITs.

Run with:
    streamlit run app.py

Data comes from local CSV caches built by the scripts/ pipeline:
    scripts/extract_bv.py   -> data/bv_quarterly.csv  (book values, from the xlsx)
    scripts/fetch_prices.py -> data/prices_daily.csv  (daily closes, from yfinance)
    scripts/build_pbv.py    -> data/pbv_daily.csv      (daily P/BV, lagged BV)

Tabs:
    Chart              - historical daily P/BV for tickers you select, with a
                          "Refresh current price" button that folds a live
                          intraday quote into the line as one more point.
    Rankings           - all mREITs' P/BV in one table, lowest to highest;
                          "Refresh live prices" re-fetches quotes for everyone.
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
from common import BV_QUARTERLY_CSV, PBV_DAILY_CSV, next_quarter_label, quarter_end_date, sorted_quarters  # noqa: E402
from update_bv import upsert_book_values  # noqa: E402

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


if not PBV_DAILY_CSV.exists():
    st.error(
        "No P/BV data found. Run the pipeline first:\n\n"
        "    cd scripts\n    python extract_bv.py\n    python fetch_prices.py --full\n    python build_pbv.py"
    )
    st.stop()

pbv_df = load_pbv()
bv_df = load_bv()
latest_bv_quarter, latest_bv = latest_bv_snapshot(bv_df)
all_tickers = sorted(pbv_df["ticker"].unique())

st.markdown("## mREIT Price / Book Value Multiples")

tab_chart, tab_rankings, tab_update = st.tabs(["📈 Chart", "📊 Rankings", "📝 Update Book Values"])

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
        f"({latest_bv_quarter}) to show where each REIT trades right now."
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
            if ticker in live_prices and ticker in latest_bv and x:
                live_pbv = live_prices[ticker] / latest_bv[ticker]
                ts_label = live_ts.strftime("%Y-%m-%d %H:%M") if live_ts else "now"
                x.append(pd.Timestamp.now())
                y.append(live_pbv)
                hover_labels.append(f"Live @ {ts_label}")

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
        fig.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5)

        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})

        if live_prices:
            shown_live = {t: p for t, p in live_prices.items() if t in selected}
            if shown_live:
                st.subheader(f"Live snapshot ({live_ts.strftime('%Y-%m-%d %H:%M:%S')})")
                live_rows = [
                    {
                        "ticker": t,
                        "live_price": shown_live[t],
                        f"{latest_bv_quarter}_book_value": latest_bv.get(t),
                        "live_pbv": shown_live[t] / latest_bv[t] if t in latest_bv else None,
                    }
                    for t in selected
                    if t in shown_live
                ]
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
        "until you refresh; refreshing fetches a live quote for every ticker."
    )
    refresh_all_clicked = st.button("🔄 Refresh live prices", key="refresh_all_prices")
    if refresh_all_clicked:
        with st.spinner("Fetching live prices for all mREITs..."):
            refresh_live_prices(all_tickers)

    live_prices = st.session_state.get("live_prices", {})
    live_ts = st.session_state.get("live_ts")
    latest_daily = pbv_df.sort_values("date").groupby("ticker").tail(1).set_index("ticker")

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
        rows.append(
            {
                "ticker": t,
                "pbv": round(pbv, 3),
                "price": round(price, 2),
                "book_value": bv,
                "bv_quarter": bv_quarter_used,
                "as_of": as_of,
                "source": source,
            }
        )

    table = pd.DataFrame(rows).sort_values("pbv").reset_index(drop=True)
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "pbv": st.column_config.NumberColumn("P/BV", format="%.2fx"),
            "price": st.column_config.NumberColumn("Price"),
            "book_value": st.column_config.NumberColumn("Book Value"),
            "bv_quarter": st.column_config.TextColumn("BV Quarter"),
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
        f"quarter is entered) -- e.g. saving Q3'26 here starts applying to Q4'26 prices."
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
            n = upsert_book_values(target_quarter, values)
            if n == 0:
                st.warning("No values entered -- nothing saved.")
            else:
                build_pbv()
                load_pbv.clear()
                load_bv.clear()
                st.success(f"Saved {n} book value(s) for {target_quarter} and refreshed P/BV.")
                st.rerun()
