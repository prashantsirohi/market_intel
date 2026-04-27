from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st


DEFAULT_DB = "./data/market_intel.duckdb"


@st.cache_data(ttl=60)
def load_events(db_path: str) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame()

    conn = duckdb.connect(db_path, read_only=True)
    try:
        return conn.execute(
            """
            SELECT
              r.created_at,
              r.symbol,
              r.primary_category,
              r.sentiment_label,
              r.importance_score,
              r.trust_score,
              r.alert_level,
              e.title,
              e.link,
              e.source,
              e.source_type,
              e.seen_count,
              e.last_seen_at
            FROM resolved_event r
            JOIN raw_event e ON e.raw_event_id = r.raw_event_id
            ORDER BY r.created_at DESC
            LIMIT 1000
            """
        ).fetchdf()
    finally:
        conn.close()


@st.cache_data(ttl=60)
def load_raw_events(db_path: str) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame()

    conn = duckdb.connect(db_path, read_only=True)
    try:
        return conn.execute(
            """
            SELECT
                id,
                title,
                symbol,
                category,
                importance,
                sentiment,
                link,
                pub_date,
                description
            FROM raw_events
            ORDER BY id DESC
            LIMIT 1000
            """
        ).fetchdf()
    finally:
        conn.close()


@st.cache_data(ttl=60)
def load_alerts(db_path: str) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame()

    conn = duckdb.connect(db_path, read_only=True)
    try:
        return conn.execute(
            """
            SELECT
              sent_at,
              channel,
              alert_status,
              error_message,
              resolved_event_id
            FROM alert_log
            ORDER BY sent_at DESC
            LIMIT 500
            """
        ).fetchdf()
    finally:
        conn.close()


def main():
    st.set_page_config(page_title="Market Intel Monitor", layout="wide", page_icon="📈")
    st.title("📈 Market Intelligence Monitor")

    db_path = st.sidebar.text_input("DuckDB path", DEFAULT_DB)
    refresh = st.sidebar.button("Refresh")
    if refresh:
        st.cache_data.clear()

    events = load_raw_events(db_path)
    alerts = load_alerts(db_path)

    if events.empty:
        st.warning("No events found. Run collection first.")
        st.code("cd src && python -c \"from market_intel.collectors import NseRssClient; ...\"")
        return

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["Overview", "Event Feed", "Alerts", "Stock View", "Sector View"]
    )

    with tab1:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Events", len(events))
        c2.metric("Critical", int((events["importance"] >= 8.5).sum()))
        c3.metric("Important", int((events["importance"] >= 7.0).sum()))
        c4.metric("Symbols", events["symbol"].nunique())

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Events by Category")
            cat_counts = events["category"].value_counts().reset_index()
            cat_counts.columns = ["category", "count"]
            st.dataframe(cat_counts, use_container_width=True, hide_index=True)

        with col2:
            st.subheader("Events by Importance")
            imp_counts = events["importance"].value_counts(bins=[0, 5, 7, 8.5, 10], sort=False).reset_index()
            imp_counts.columns = ["importance", "count"]
            st.dataframe(imp_counts, use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Event Feed")

        col1, col2, col3 = st.columns(3)
        symbols = ["All"] + sorted([x for x in events["symbol"].dropna().unique() if x])
        levels = ["All", "High (>=7)", "Medium (5-7)", "Low (<5)"]
        categories = ["All"] + sorted([x for x in events["category"].dropna().unique() if x])

        symbol = col1.selectbox("Symbol", symbols)
        level = col2.selectbox("Importance", levels)
        category = col3.selectbox("Category", categories)

        filtered = events.copy()
        if symbol != "All":
            filtered = filtered[filtered["symbol"] == symbol]
        if level == "High (>=7)":
            filtered = filtered[filtered["importance"] >= 7]
        elif level == "Medium (5-7)":
            filtered = filtered[(filtered["importance"] >= 5) & (filtered["importance"] < 7)]
        elif level == "Low (<5)":
            filtered = filtered[filtered["importance"] < 5]
        if category != "All":
            filtered = filtered[filtered["category"] == category]
        
        # Always filter out NAV
        filtered = filtered[filtered["category"] != "mutual_fund_nav"]

        st.dataframe(
            filtered[
                [
                    "id",
                    "symbol",
                    "category",
                    "importance",
                    "sentiment",
                    "title",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "title": st.column_config.LinkColumn("Title", display_text="Link"),
            },
        )

    with tab3:
        st.subheader("Alert Log")
        if alerts.empty:
            st.info("No alerts sent yet.")
        else:
            status_counts = alerts["alert_status"].value_counts()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Sent", int((alerts["alert_status"] == "sent").sum()))
            c2.metric("Pending", int((alerts["alert_status"] == "pending").sum()))
            c3.metric("Failed", int((alerts["alert_status"] == "failed").sum()))
            c4.metric("Skipped", int((alerts["alert_status"] == "skipped").sum()))

            st.dataframe(
                alerts[
                    [
                        "sent_at",
                        "channel",
                        "alert_status",
                        "resolved_event_id",
                        "error_message",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

with tab4:
        st.subheader("Stock View")
        
        # Get unique symbols from filtered events
        event_symbols = sorted([x for x in events["symbol"].dropna().unique() if x and len(x) >= 2])
        
        if not event_symbols:
            st.info("No symbols found. Symbols are extracted from event GUIDs.")
        else:
            symbol = st.selectbox("Select Symbol", event_symbols)
            stock_df = events[events["symbol"] == symbol]

            c1, c2, c3 = st.columns(3)
            c1.metric("Events", len(stock_df))
            c2.metric("Critical", int((stock_df["importance"] >= 8.5).sum()))
            c3.metric("Important", int((stock_df["importance"] >= 7).sum()))

            st.subheader("Recent Events")
            st.dataframe(
                stock_df[
                    [
                        "id",
                        "category",
                        "importance",
                        "sentiment",
                        "title",
                    ]
                ],
use_container_width=True,
            hide_index=True,
        )

    with tab5:
        st.subheader("Sector View")
        sector_counts = (
            events[events["category"] != "mutual_fund_nav"]["category"]
            .value_counts()
            .reset_index()
        )
        sector_counts.columns = ["category", "count"]
        st.dataframe(sector_counts, use_container_width=True, hide_index=True)

        st.subheader("Positive vs Negative Events")
        sentiment_counts = events["sentiment"].value_counts()
        st.bar_chart(sentiment_counts)


if __name__ == "__main__":
    main()