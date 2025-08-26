import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sys
import os
from collections import defaultdict
import json

# Add the parent directory to the path to import the database module
# This is a bit of a hack, a better solution would be to have a proper package structure
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app')))

from database import db
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Monitoring Report", layout="wide")

st.title("📈 Pump.fun Monitoring Report")

# --- Refresh Controls ---
col1, col2, col3 = st.columns([0.2, 0.2, 0.6])
with col1:
    if st.button("🔄 Refresh"):
        st.rerun()
with col2:
    auto_refresh = st.checkbox("Auto-refresh (30s)", value=True)

if auto_refresh:
    st_autorefresh(interval=30 * 1000, key="datarefresh")

st.write(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# --- Potentially Good New Tokens ---
st.header("🌟 Potentiellement bons nouveaux tokens (dernières 30 minutes)")

new_potential_tokens = db.get_new_potential_tokens_with_details(minutes_since=30)

if not new_potential_tokens:
    st.info("Aucun nouveau token prometteur trouvé dans les 30 dernières minutes.")
else:
    df_new_potential = pd.DataFrame(new_potential_tokens)
    
    # Format data for display
    df_new_potential['bonding_curve'] = df_new_potential['bonding_curve_progress'].apply(
        lambda x: f"{x * 100:.2f}%" if pd.notna(x) else "N/A"
    )
    df_new_potential['discovered_at'] = pd.to_datetime(df_new_potential['row_created_at']).dt.strftime('%H:%M:%S')
    df_new_potential['market_cap_fmt'] = df_new_potential['usd_market_cap'].apply(
        lambda x: f"${x:,.0f}" if pd.notna(x) and x > 0 else "N/A"
    )
    df_new_potential['updated_at_fmt'] = pd.to_datetime(df_new_potential['last_updated_pumpfun']).dt.strftime('%H:%M:%S')

    # Select and rename columns
    df_display_potential = df_new_potential[[
        'address', 'name', 'symbol', 'creator', 'score', 'bonding_curve', 'market_cap_fmt', 'discovered_at', 'updated_at_fmt'
    ]]
    df_display_potential.rename(columns={
        'address': 'Token Address',
        'name': 'Name',
        'symbol': 'Symbol',
        'creator': 'Creator',
        'score': 'Rugcheck Score',
        'bonding_curve': 'Bonding Curve',
        'market_cap_fmt': 'Market Cap',
        'discovered_at': 'Discovered At',
        'updated_at_fmt': 'Last Updated'
    }, inplace=True)

    st.dataframe(df_display_potential, use_container_width=True)

st.divider()


# --- Helper Functions ---

def get_time_since(minutes):
    return datetime.now() - timedelta(minutes=minutes)

# --- Main App ---

# Time intervals for the reports
intervals = {
    "5 minutes": 5,
    "30 minutes": 30,
    "1 hour": 60,
    "6 hours": 360,
    "24 hours": 1440,
    "7 days": 10080,
}

# --- New Token Discovery Rate ---
st.header("🚀 New Token Discovery Rate")
cols = st.columns(len(intervals))

for i, (label, minutes) in enumerate(intervals.items()):
    since_time = get_time_since(minutes)
    count = db.get_new_tokens_count_since(since_time)
    with cols[i]:
        st.metric(label=label, value=count)

# --- Blacklisted Tokens Rate ---
st.header("🛡️ Blacklisted Tokens Rate")
cols = st.columns(len(intervals))

for i, (label, minutes) in enumerate(intervals.items()):
    since_time = get_time_since(minutes)
    count = db.get_blacklisted_tokens_count_since(since_time)
    with cols[i]:
        st.metric(label=label, value=count)

# --- Non-Blacklisted New Tokens (Score >= 1) ---
st.header("✅ Nouveaux Tokens Non-Blacklistés (Score Valide >= 1)")
cols = st.columns(len(intervals))

for i, (label, minutes) in enumerate(intervals.items()):
    since_time = get_time_since(minutes)
    count = db.get_non_blacklisted_tokens_count_with_valid_score_since(since_time)
    with cols[i]:
        st.metric(label=label, value=count)

# --- Non-Blacklisted New Tokens (API Error) ---
st.header("⚠️ Nouveaux Tokens Non-Blacklistés (Erreur API)")
cols = st.columns(len(intervals))

for i, (label, minutes) in enumerate(intervals.items()):
    since_time = get_time_since(minutes)
    count = db.get_non_blacklisted_tokens_count_with_api_error_since(since_time)
    with cols[i]:
        st.metric(label=label, value=count)

st.divider()

# --- Creator-Centric Report ---
st.header("👨‍💻 Creator-Centric Report")

filter_invalid_score = st.checkbox("Hide tokens with score = -1", value=True)

creator_reports = db.get_creator_token_reports()

if not creator_reports:
    st.warning("No creator reports found in the database yet.")
else:
    # Create a DataFrame from the reports
    df = pd.DataFrame(creator_reports)

    # Apply filter if checked
    if filter_invalid_score:
        df = df[df['score'] != -1]

    if df.empty:
        st.warning("No tokens to display with the current filter.")
    else:
        # Create the summary table
        summary_df = df.groupby('creator').agg(
            total_tokens=('address', 'count'),
            blacklisted_tokens=('is_blacklisted', lambda x: x.sum())
        ).reset_index()
        summary_df.rename(columns={
            'creator': 'Creator Address',
            'total_tokens': 'Total Tokens',
            'blacklisted_tokens': 'Blacklisted Tokens'
        }, inplace=True)
        
        st.subheader("Creator Summary")
        st.dataframe(summary_df.sort_values(by="Total Tokens", ascending=False), use_container_width=True)

        st.divider()

        # Creator detail view
        st.subheader("Creator Details")
        creator_list = ["Select a creator..."] + summary_df['Creator Address'].tolist()
        selected_creator = st.selectbox("Select a creator to view their tokens:", creator_list)

        if selected_creator != "Select a creator...":
            creator_tokens_df = df[df['creator'] == selected_creator]
            
            df_display = creator_tokens_df[['address', 'score', 'is_blacklisted']].copy()
            df_display.rename(columns={
                'address': 'Token Address',
                'score': 'Rugcheck Score',
                'is_blacklisted': 'Blacklisted'
            }, inplace=True)

            st.dataframe(df_display.style.apply(
                lambda x: ['background-color: #ffcccc' if x.Blacklisted else '' for i in x],
                axis=1
            ), use_container_width=True)

st.divider()

# --- Non-Blacklisted Token Details ---
st.header("🔍 Non-Blacklisted Token Details")

token_details = db.get_non_blacklisted_token_details()

if not token_details:
    st.warning("No non-blacklisted tokens with rugcheck reports found.")
else:
    df_details = pd.DataFrame(token_details)

    # Process data for display
    def format_risks(risks_json):
        if not risks_json:
            return "No risks"
        try:
            risks_list = json.loads(risks_json)
            return ", ".join([r.get('name', 'Unknown') for r in risks_list])
        except (json.JSONDecodeError, TypeError):
            return "Invalid risk format"

    def format_holders(holders_json):
        if not holders_json:
            return "N/A"
        try:
            holders_list = json.loads(holders_json)
            if not holders_list:
                return "N/A"
            top_5_pct = sum(h.get('percentage', 0) for h in holders_list[:5])
            return f"Top 5: {top_5_pct:.2f}%"
        except (json.JSONDecodeError, TypeError):
            return "Invalid holder format"

    df_details['risks_list'] = df_details['risks'].apply(format_risks)
    df_details['holder_dist'] = df_details['top_holders'].apply(format_holders)
    # Format bonding curve progress
    df_details['bonding_curve_progress_fmt'] = df_details['bonding_curve_progress'].apply(
        lambda x: f"{x * 100:.2f}%" if pd.notna(x) else "N/A"
    )
    
    # Format date
    df_details['rugcheck_updated_at'] = pd.to_datetime(df_details['rugcheck_updated_at']).dt.strftime('%Y-%m-%d %H:%M:%S')

    df_display_details = df_details[[
        'address', 'creator', 'score', 'risks_list', 
        'holders_count', 'holder_dist', 'bonding_curve_progress_fmt', 'rugcheck_updated_at'
    ]]
    df_display_details.rename(columns={
        'address': 'Token Address',
        'creator': 'Creator',
        'score': 'Rugcheck Score',
        'risks_list': 'Risks',
        'holders_count': 'Holders',
        'holder_dist': 'Holder Distribution',
        'bonding_curve_progress_fmt': 'Bonding Curve Progress',
        'rugcheck_updated_at': 'Rugcheck Updated At'
    }, inplace=True)

    st.dataframe(df_display_details, use_container_width=True)

    st.divider()
    st.header("💯 Tokens with Completed Bonding Curve")
    
    # Filter for tokens where bonding_curve_progress is 1 (or 1.0)
    df_completed = df_details[df_details['bonding_curve_progress'] == 1]
    
    if df_completed.empty:
        st.info("No non-blacklisted tokens have reached 100% bonding curve progress yet.")
    else:
        # Filter the already formatted and renamed dataframe to show only completed tokens
        completed_indices = df_completed.index
        st.dataframe(df_display_details.loc[completed_indices], use_container_width=True)
