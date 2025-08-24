import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sys
import os
from collections import defaultdict

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

# --- Non-Blacklisted New Tokens ---
st.header("✅ Non-Blacklisted New Tokens")
cols = st.columns(len(intervals))

for i, (label, minutes) in enumerate(intervals.items()):
    since_time = get_time_since(minutes)
    count = db.get_non_blacklisted_tokens_count_since(since_time)
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
