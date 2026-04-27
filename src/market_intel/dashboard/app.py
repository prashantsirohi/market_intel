from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st


DEFAULT_DB = "./data/market_intel.duckdb"


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
        return

    show_ignored = st.sidebar.checkbox("Show ignored events", value=False)
    if not show_ignored:
        events = events[events["alert_level"] != "ignore"]

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
        all_categories = sorted([x for x in events["category"].dropna().unique() if x])
        if "mutual_fund_nav" in all_categories:
            all_categories.remove("mutual_fund_nav")
        categories = ["All"] + all_categories
        levels = ["All", "High (>=7)", "Medium (5-7)", "Low (<5)"]

        symbol = col1.selectbox("Symbol", ["All"] + sorted([x for x in events["symbol"].dropna().unique() if x]))
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

        st.dataframe(
            filtered[["id", "symbol", "category", "importance", "sentiment", "title"]],
            use_container_width=True,
            hide_index=True,
        )

    with tab3:
        st.subheader("Alert Log")
        if alerts.empty:
            st.info("No alerts sent yet.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Sent", int((alerts["alert_status"] == "sent").sum()))
            c2.metric("Pending", int((alerts["alert_status"] == "pending").sum()))
            c3.metric("Failed", int((alerts["alert_status"] == "failed").sum()))
            c4.metric("Skipped", int((alerts["alert_status"] == "skipped").sum()))

            st.dataframe(
                alerts[["sent_at", "channel", "alert_status", "resolved_event_id", "error_message"]],
                use_container_width=True,
                hide_index=True,
            )

    with tab4:
        st.subheader("Stock View")
        event_symbols = sorted([x for x in events["symbol"].dropna().unique() if x and len(x) >= 2])

        if not event_symbols:
            st.info("No symbols found.")
        else:
            symbol = st.selectbox("Select Symbol", event_symbols)
            stock_df = events[events["symbol"] == symbol]

            c1, c2, c3 = st.columns(3)
            c1.metric("Events", len(stock_df))
            c2.metric("Critical", int((stock_df["importance"] >= 8.5).sum()))
            c3.metric("Important", int((stock_df["importance"] >= 7).sum()))

            st.dataframe(
                stock_df[["id", "category", "importance", "sentiment", "title"]],
                use_container_width=True,
                hide_index=True,
            )

    with tab5:
        st.subheader("Sector View")
        filtered_events = events[events["category"] != "mutual_fund_nav"]
        sector_counts = filtered_events["category"].value_counts().reset_index()
        sector_counts.columns = ["category", "count"]
        st.dataframe(sector_counts, use_container_width=True, hide_index=True)

        st.subheader("Positive vs Negative Events")
        sentiment_counts = filtered_events["sentiment"].value_counts()
        st.bar_chart(sentiment_counts)


if __name__ == "__main__":
    main()