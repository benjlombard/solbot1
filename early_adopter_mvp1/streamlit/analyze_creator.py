import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta

# Database connection
def connect_to_db(db_path):
    """Connect to the SQLite database."""
    try:
        conn = sqlite3.connect(db_path)
        return conn
    except sqlite3.Error as e:
        st.error(f"Database connection error: {e}")
        raise

# Fetch all tokens from creator_token_history
def get_tokens(conn):
    query = """
    SELECT 
        id, creator_address, token_address, token_name, token_symbol, 
        launch_date, outcome_type, roi_24h, peak_market_cap, 
        survival_time_hours, is_success, contributed_to_blacklist, 
        notes, created_at, current_market_cap, last_updated_from_api
    FROM creator_token_history
    ORDER BY id ASC
    """
    try:
        df = pd.read_sql_query(query, conn)
        return df
    except sqlite3.Error as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

# Fetch creator stats for indicators
def get_creator_stats(conn):
    query = """
    SELECT 
        creator_address,
        COUNT(*) as token_count,
        MIN(launch_date) as first_launch,
        MAX(launch_date) as last_launch
    FROM creator_token_history
    GROUP BY creator_address
    """
    try:
        df = pd.read_sql_query(query, conn)
        return df
    except sqlite3.Error as e:
        st.error(f"Error fetching creator stats: {e}")
        return pd.DataFrame()

def main():
    st.set_page_config(page_title="Tokens Analysis Report", layout="wide")
    st.title("📊 Tokens Analysis Report")
    st.write(f"Last refreshed: 2025-09-02 21:58:00 CEST")

    # Database path
    db_path = "early_adopter.db"
    conn = connect_to_db(db_path)

    # --- Key Indicators ---
    st.header("🔑 Key Indicators")
    df_tokens = get_tokens(conn)
    df_creators = get_creator_stats(conn)

    if df_tokens.empty:
        st.warning("No tokens found in creator_token_history.")
    else:
        # Convert launch_date and created_at to datetime
        df_tokens['launch_date'] = pd.to_datetime(df_tokens['launch_date'], format='mixed', errors='coerce')
        df_tokens['created_at'] = pd.to_datetime(df_tokens['created_at'], format='mixed', errors='coerce')
        df_tokens['last_updated_from_api'] = pd.to_datetime(df_tokens['last_updated_from_api'], format='mixed', errors='coerce')

        # Check for unparseable dates
        if df_tokens['launch_date'].isna().any():
            st.warning("Some launch_date values could not be parsed and are set to NaT.")

        # Calculate market cap percentage change
        df_tokens['market_cap_change_pct'] = df_tokens.apply(
            lambda row: ((row['current_market_cap'] - row['peak_market_cap']) / row['peak_market_cap'] * 100)
            if pd.notnull(row['peak_market_cap']) and row['peak_market_cap'] != 0 else 0.0, axis=1
        )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Tokens", len(df_tokens))
        with col2:
            st.metric("Unique Creators", len(df_creators))
        with col3:
            recent_tokens = len(df_tokens[df_tokens['launch_date'] > datetime(2025, 9, 2, 21, 58) - timedelta(days=7)])
            st.metric("Tokens Launched (Last 7 Days)", recent_tokens)
        with col4:
            top_creator = df_creators.loc[df_creators['token_count'].idxmax(), 'creator_address'] if not df_creators.empty else "N/A"
            st.metric("Top Creator (Most Tokens)", top_creator[:8] + "..." if top_creator != "N/A" else "N/A")

    # --- Filtered Table ---
    st.header("🔍 Token Analysis Table")
    
    if not df_tokens.empty:
        # Prepare DataFrame for display
        df_display = df_tokens.copy()
        df_display['launch_date'] = df_display['launch_date'].dt.strftime('%Y-%m-%d %H:%M:%S')
        df_display['created_at'] = df_display['created_at'].dt.strftime('%Y-%m-%d %H:%M:%S')
        df_display['last_updated_from_api'] = df_display['last_updated_from_api'].dt.strftime('%Y-%m-%d %H:%M:%S')
        df_display['current_market_cap'] = df_display['current_market_cap'].apply(lambda x: f"${x:,.2f}" if pd.notnull(x) else "N/A")
        df_display['peak_market_cap'] = df_display['peak_market_cap'].apply(lambda x: f"${x:,.2f}" if pd.notnull(x) else "N/A")
        df_display['survival_time_hours'] = df_display['survival_time_hours'].apply(lambda x: f"{x:,.2f}" if pd.notnull(x) else "N/A")
        df_display['market_cap_change_pct'] = df_display['market_cap_change_pct'].apply(lambda x: f"{x:,.2f}%" if pd.notnull(x) else "N/A")

        # Filters
        st.subheader("Filters")
        col_f1, col_f2, col_f3 = st.columns(3)
        col_f4, col_f5, col_f6 = st.columns(3)
        
        with col_f1:
            creator_filter = st.multiselect(
                "Filter by Creator Address",
                options=df_display['creator_address'].unique(),
                default=[]
            )
        with col_f2:
            symbol_filter = st.multiselect(
                "Filter by Token Symbol",
                options=df_display['token_symbol'].unique(),
                default=[]
            )
        with col_f3:
            earliest_date = pd.to_datetime(df_display['launch_date'], errors='coerce').min().date()
            default_start = earliest_date if earliest_date else (datetime(2025, 9, 2).date() - timedelta(days=30))
            date_range = st.date_input(
                "Filter by Launch Date",
                value=(default_start, datetime(2025, 9, 2).date()),
                min_value=earliest_date if earliest_date else datetime(2024, 1, 1).date(),
                max_value=datetime(2025, 9, 2).date()
            )
        with col_f4:
            peak_market_cap_float = df_display['peak_market_cap'].str.replace('$', '').str.replace(',', '').replace('N/A', None).astype(float)
            min_peak = peak_market_cap_float.min() if not peak_market_cap_float.isna().all() else 0.0
            max_peak = peak_market_cap_float.max() if not peak_market_cap_float.isna().all() else 0.0
            if min_peak == max_peak or pd.isna(min_peak) or pd.isna(max_peak):
                st.write(f"Peak Market Cap: All valid values are identical ({min_peak:,.2f})")
                peak_market_cap_range = (min_peak, max_peak)
            else:
                peak_market_cap_range = st.slider(
                    "Filter by Peak Market Cap ($)",
                    min_value=float(min_peak),
                    max_value=float(max_peak),
                    value=(float(min_peak), float(max_peak)),
                    step=100.0
                )
        with col_f5:
            survival_time_float = df_display['survival_time_hours'].str.replace(',', '').replace('N/A', None).astype(float)
            min_survival = survival_time_float.min() if not survival_time_float.isna().all() else 0.0
            max_survival = survival_time_float.max() if not survival_time_float.isna().all() else 0.0
            if min_survival == max_survival or pd.isna(min_survival) or pd.isna(max_survival):
                st.write(f"Survival Time: All valid values are identical ({min_survival:,.2f} hours)")
                survival_time_range = (min_survival, max_survival)
            else:
                survival_time_range = st.slider(
                    "Filter by Survival Time (Hours)",
                    min_value=float(min_survival),
                    max_value=float(max_survival),
                    value=(float(min_survival), float(max_survival)),
                    step=0.1
                )
        with col_f6:
            market_cap_change_float = df_display['market_cap_change_pct'].str.replace('%', '').str.replace(',', '').replace('N/A', None).astype(float)
            min_change = market_cap_change_float.min() if not market_cap_change_float.isna().all() else 0.0
            max_change = market_cap_change_float.max() if not market_cap_change_float.isna().all() else 0.0
            if min_change == max_change or pd.isna(min_change) or pd.isna(max_change):
                st.write(f"Market Cap Change: All valid values are identical ({min_change:,.2f}%)")
                market_cap_change_range = (min_change, max_change)
            else:
                market_cap_change_range = st.slider(
                    "Filter by Market Cap Change (%)",
                    min_value=float(min_change),
                    max_value=float(max_change),
                    value=(float(min_change), float(max_change)),
                    step=1.0
                )

        # Apply filters
        filtered_df = df_display
        if creator_filter:
            filtered_df = filtered_df[filtered_df['creator_address'].isin(creator_filter)]
        if symbol_filter:
            filtered_df = filtered_df[filtered_df['token_symbol'].isin(symbol_filter)]
        if len(date_range) == 2:
            start_date, end_date = date_range
            filtered_df = filtered_df[
                (pd.to_datetime(filtered_df['launch_date'], errors='coerce') >= pd.Timestamp(start_date)) &
                (pd.to_datetime(filtered_df['launch_date'], errors='coerce') <= pd.Timestamp(end_date) + pd.Timedelta(days=1))
            ]
        if not (min_peak == max_peak or pd.isna(min_peak) or pd.isna(max_peak)):
            filtered_df = filtered_df[
                (filtered_df['peak_market_cap'].str.replace('$', '').str.replace(',', '').replace('N/A', None).astype(float) >= peak_market_cap_range[0]) &
                (filtered_df['peak_market_cap'].str.replace('$', '').str.replace(',', '').replace('N/A', None).astype(float) <= peak_market_cap_range[1])
            ]
        if not (min_survival == max_survival or pd.isna(min_survival) or pd.isna(max_survival)):
            filtered_df = filtered_df[
                (filtered_df['survival_time_hours'].str.replace(',', '').replace('N/A', None).astype(float) >= survival_time_range[0]) &
                (filtered_df['survival_time_hours'].str.replace(',', '').replace('N/A', None).astype(float) <= survival_time_range[1])
            ]
        if not (min_change == max_change or pd.isna(min_change) or pd.isna(max_change)):
            filtered_df = filtered_df[
                (filtered_df['market_cap_change_pct'].str.replace('%', '').str.replace(',', '').replace('N/A', None).astype(float) >= market_cap_change_range[0]) &
                (filtered_df['market_cap_change_pct'].str.replace('%', '').str.replace(',', '').replace('N/A', None).astype(float) <= market_cap_change_range[1])
            ]

        # Select columns for display
        display_columns = [
            'token_address', 'token_name', 'token_symbol', 'creator_address',
            'launch_date', 'outcome_type', 'current_market_cap', 'peak_market_cap',
            'survival_time_hours', 'market_cap_change_pct', 'last_updated_from_api'
        ]
        st.dataframe(
            filtered_df[display_columns].rename(columns={
                'token_address': 'Token Address',
                'token_name': 'Name',
                'token_symbol': 'Symbol',
                'creator_address': 'Creator Address',
                'launch_date': 'Launch Date',
                'outcome_type': 'Outcome',
                'current_market_cap': 'Current Market Cap',
                'peak_market_cap': 'Peak Market Cap',
                'survival_time_hours': 'Survival Time (Hours)',
                'market_cap_change_pct': 'Market Cap Change (%)',
                'last_updated_from_api': 'Last API Update'
            }),
            use_container_width=True
        )

        # Download button
        csv = filtered_df[display_columns].to_csv(index=False)
        st.download_button(
            label="Download Filtered Data as CSV",
            data=csv,
            file_name="tokens_report.csv",
            mime="text/csv"
        )

    # Close database connection
    conn.close()

if __name__ == "__main__":
    main()