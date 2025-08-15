import sqlite3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st
from datetime import datetime, timedelta
import numpy as np
from typing import Dict, List, Tuple, Optional

class TokenHistoryAnalyzer:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        
    def connect(self) -> bool:
        """Establishes connection to the database"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            return True
        except Exception as e:
            st.error(f"Database connection error: {e}")
            return False
    
    def get_tokens_with_history(self) -> List[str]:
        """Get list of tokens that have historical data"""
        if not self.conn:
            return []
        
        query = """
        SELECT DISTINCT th.token_address, t.symbol, t.name,
               COUNT(th.id) as snapshot_count,
               MIN(th.snapshot_timestamp) as first_snapshot,
               MAX(th.snapshot_timestamp) as last_snapshot
        FROM tokens_history th
        LEFT JOIN tokens t ON th.token_address = t.address
        GROUP BY th.token_address
        ORDER BY snapshot_count DESC, last_snapshot DESC
        """
        
        df = pd.read_sql_query(query, self.conn)
        return df.to_dict('records') if not df.empty else []
    
    def get_token_history_overview(self) -> Dict:
        """Get overview statistics for token history data"""
        if not self.conn:
            return {}
        
        query = """
        SELECT 
            COUNT(DISTINCT token_address) as unique_tokens_with_history,
            COUNT(*) as total_snapshots,
            AVG(viability_score) as avg_viability_score,
            AVG(risk_score) as avg_risk_score,
            AVG(momentum_score) as avg_momentum_score,
            MIN(snapshot_timestamp) as oldest_snapshot,
            MAX(snapshot_timestamp) as newest_snapshot,
            
            -- Score distributions
            COUNT(CASE WHEN viability_score >= 80 THEN 1 END) as high_viability_snapshots,
            COUNT(CASE WHEN viability_score >= 60 AND viability_score < 80 THEN 1 END) as medium_viability_snapshots,
            COUNT(CASE WHEN viability_score < 40 THEN 1 END) as low_viability_snapshots,
            COUNT(CASE WHEN risk_score >= 70 THEN 1 END) as high_risk_snapshots,
            COUNT(CASE WHEN momentum_score > 50 THEN 1 END) as positive_momentum_snapshots,
            COUNT(CASE WHEN momentum_score < -50 THEN 1 END) as negative_momentum_snapshots,
            
            -- Recent activity (24h)
            COUNT(CASE WHEN snapshot_timestamp >= strftime('%s', 'now') - 86400 THEN 1 END) as snapshots_24h,
            COUNT(DISTINCT CASE WHEN snapshot_timestamp >= strftime('%s', 'now') - 86400 THEN token_address END) as active_tokens_24h,
            
            -- Delta analysis
            AVG(ABS(price_delta_usd)) as avg_abs_price_delta,
            AVG(market_cap_delta) as avg_market_cap_delta,
            AVG(volume_24h_delta) as avg_volume_delta
            
        FROM tokens_history
        """
        
        result = pd.read_sql_query(query, self.conn)
        return result.iloc[0].to_dict() if len(result) > 0 else {}
    
    def get_token_detailed_history(self, token_address: str, limit: int = 100) -> pd.DataFrame:
        """Get detailed historical data for a specific token"""
        if not self.conn:
            return pd.DataFrame()
        
        query = """
        SELECT 
            th.*,
            datetime(th.snapshot_timestamp, 'unixepoch') as snapshot_datetime,
            t.symbol as current_symbol,
            t.name as current_name
        FROM tokens_history th
        LEFT JOIN tokens t ON th.token_address = t.address
        WHERE th.token_address = ?
        ORDER BY th.snapshot_timestamp DESC
        LIMIT ?
        """
        
        return pd.read_sql_query(query, self.conn, params=[token_address, limit])
    
    def get_score_trends_analysis(self, days: int = 7) -> pd.DataFrame:
        """Analyze score trends over time"""
        if not self.conn:
            return pd.DataFrame()
        
        cutoff_timestamp = datetime.now().timestamp() - (days * 86400)
        
        query = """
        SELECT 
            date(datetime(snapshot_timestamp, 'unixepoch')) as snapshot_date,
            AVG(viability_score) as avg_viability,
            AVG(risk_score) as avg_risk,
            AVG(momentum_score) as avg_momentum,
            COUNT(*) as snapshot_count,
            COUNT(DISTINCT token_address) as unique_tokens,
            
            -- Performance categories
            COUNT(CASE WHEN viability_score >= 70 THEN 1 END) as high_performers,
            COUNT(CASE WHEN viability_score < 40 THEN 1 END) as low_performers,
            COUNT(CASE WHEN risk_score >= 70 THEN 1 END) as high_risk_count,
            
            -- Market metrics
            AVG(market_cap) as avg_market_cap,
            AVG(volume_24h) as avg_volume_24h,
            AVG(price_usd) as avg_price,
            AVG(holder_count) as avg_holders
            
        FROM tokens_history
        WHERE snapshot_timestamp >= ?
        GROUP BY date(datetime(snapshot_timestamp, 'unixepoch'))
        ORDER BY snapshot_date DESC
        """
        
        return pd.read_sql_query(query, self.conn, params=[cutoff_timestamp])
    
    def get_top_performing_tokens(self, metric: str = 'viability_score', limit: int = 20) -> pd.DataFrame:
        """Get top performing tokens based on latest scores"""
        if not self.conn:
            return pd.DataFrame()
        
        # Get latest snapshot for each token
        query = f"""
        WITH latest_snapshots AS (
            SELECT 
                token_address,
                MAX(snapshot_timestamp) as latest_timestamp
            FROM tokens_history
            GROUP BY token_address
        ),
        latest_data AS (
            SELECT 
                th.*,
                t.symbol as current_symbol,
                t.name as current_name,
                t.market_cap as current_market_cap,
                t.is_dead
            FROM tokens_history th
            JOIN latest_snapshots ls ON th.token_address = ls.token_address 
                                    AND th.snapshot_timestamp = ls.latest_timestamp
            LEFT JOIN tokens t ON th.token_address = t.address
            WHERE t.is_dead = 0 OR t.is_dead IS NULL
        )
        SELECT * FROM latest_data
        ORDER BY {metric} DESC
        LIMIT ?
        """
        
        return pd.read_sql_query(query, self.conn, params=[limit])
    
    def get_token_comparison_data(self, token_addresses: List[str], days: int = 7) -> pd.DataFrame:
        """Compare multiple tokens over time"""
        if not self.conn or not token_addresses:
            return pd.DataFrame()
        
        cutoff_timestamp = datetime.now().timestamp() - (days * 86400)
        placeholders = ','.join(['?' for _ in token_addresses])
        
        query = f"""
        SELECT 
            th.token_address,
            th.snapshot_timestamp,
            datetime(th.snapshot_timestamp, 'unixepoch') as snapshot_datetime,
            th.viability_score,
            th.risk_score,
            th.momentum_score,
            th.price_usd,
            th.market_cap,
            th.volume_24h,
            th.holder_count,
            t.symbol,
            t.name
        FROM tokens_history th
        LEFT JOIN tokens t ON th.token_address = t.address
        WHERE th.token_address IN ({placeholders})
        AND th.snapshot_timestamp >= ?
        ORDER BY th.snapshot_timestamp DESC
        """
        
        params = token_addresses + [cutoff_timestamp]
        return pd.read_sql_query(query, self.conn, params=params)
    
    def get_momentum_analysis(self, days: int = 7) -> pd.DataFrame:
        """Analyze momentum trends and identify trending tokens"""
        if not self.conn:
            return pd.DataFrame()
        
        cutoff_timestamp = datetime.now().timestamp() - (days * 86400)
        
        query = """
        WITH recent_data AS (
            SELECT 
                token_address,
                snapshot_timestamp,
                momentum_score,
                viability_score,
                price_delta_usd,
                market_cap_delta,
                volume_24h_delta,
                holder_count_delta,
                ROW_NUMBER() OVER (PARTITION BY token_address ORDER BY snapshot_timestamp DESC) as rn
            FROM tokens_history
            WHERE snapshot_timestamp >= ?
        ),
        momentum_stats AS (
            SELECT 
                token_address,
                AVG(momentum_score) as avg_momentum,
                MAX(momentum_score) as max_momentum,
                MIN(momentum_score) as min_momentum,
                COUNT(*) as snapshot_count,
                AVG(price_delta_usd) as avg_price_delta,
                AVG(viability_score) as avg_viability,
                
                -- Trend direction (comparing first vs last)
                FIRST_VALUE(momentum_score) OVER (PARTITION BY token_address ORDER BY snapshot_timestamp DESC) as latest_momentum,
                LAST_VALUE(momentum_score) OVER (PARTITION BY token_address ORDER BY snapshot_timestamp DESC 
                    RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as earliest_momentum
                    
            FROM recent_data
            GROUP BY token_address
            HAVING snapshot_count >= 3
        )
        SELECT 
            ms.*,
            t.symbol,
            t.name,
            t.market_cap as current_market_cap,
            (ms.latest_momentum - ms.earliest_momentum) as momentum_trend
        FROM momentum_stats ms
        LEFT JOIN tokens t ON ms.token_address = t.address
        WHERE t.is_dead = 0 OR t.is_dead IS NULL
        ORDER BY ms.avg_momentum DESC
        """
        
        return pd.read_sql_query(query, self.conn, params=[cutoff_timestamp])

def format_large_number(num: float) -> str:
    """Format large numbers for display"""
    if num is None or pd.isna(num):
        return "N/A"
    
    if abs(num) >= 1000000000:
        return f"{num/1000000000:.2f}B"
    elif abs(num) >= 1000000:
        return f"{num/1000000:.2f}M"
    elif abs(num) >= 1000:
        return f"{num/1000:.2f}K"
    else:
        return f"{num:.2f}"

def format_percentage(num: float) -> str:
    """Format percentage values"""
    if num is None or pd.isna(num):
        return "N/A"
    return f"{num:.1f}%"

def format_currency(num: float) -> str:
    """Format currency values"""
    if num is None or pd.isna(num):
        return "N/A"
    
    if abs(num) < 0.01:
        return f"${num:.6f}"
    elif abs(num) < 1:
        return f"${num:.4f}"
    else:
        return f"${num:.2f}"

def get_score_color(score: float, score_type: str) -> str:
    """Get color based on score value and type"""
    if pd.isna(score):
        return "gray"
    
    if score_type == "viability":
        if score >= 80:
            return "darkgreen"
        elif score >= 60:
            return "green"
        elif score >= 40:
            return "orange"
        else:
            return "red"
    elif score_type == "risk":
        if score >= 70:
            return "red"
        elif score >= 50:
            return "orange"
        elif score >= 30:
            return "yellow"
        else:
            return "green"
    elif score_type == "momentum":
        if score > 50:
            return "darkgreen"
        elif score > 0:
            return "green"
        elif score > -50:
            return "orange"
        else:
            return "red"
    
    return "gray"

def display_token_history_analytics(analyzer: TokenHistoryAnalyzer, selected_token: Optional[str] = None):
    """Display the token history analytics dashboard"""
    
    st.header("📈 Token History Analytics")
    st.markdown("*Historical analysis and trends for token performance metrics*")
    
    # === OVERVIEW METRICS ===
    with st.spinner("📊 Loading historical data..."):
        overview = analyzer.get_token_history_overview()
        tokens_with_history = analyzer.get_tokens_with_history()
    
    if not overview:
        st.error("❌ No historical data found")
        return
    
    # === GLOBAL METRICS ===
    st.subheader("📊 Historical Data Overview")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        st.metric(
            "🪙 Tokens Tracked",
            format_large_number(overview.get('unique_tokens_with_history', 0))
        )
    
    with col2:
        st.metric(
            "📸 Total Snapshots",
            format_large_number(overview.get('total_snapshots', 0))
        )
    
    with col3:
        st.metric(
            "📈 24h Snapshots",
            format_large_number(overview.get('snapshots_24h', 0)),
            delta=f"{overview.get('active_tokens_24h', 0)} tokens"
        )
    
    with col4:
        avg_viability = overview.get('avg_viability_score', 0)
        st.metric(
            "💪 Avg Viability",
            f"{avg_viability:.1f}",
            delta="Global average"
        )
    
    with col5:
        avg_risk = overview.get('avg_risk_score', 0)
        st.metric(
            "⚠️ Avg Risk",
            f"{avg_risk:.1f}",
            delta="Global average"
        )
    
    with col6:
        avg_momentum = overview.get('avg_momentum_score', 0)
        momentum_emoji = "📈" if avg_momentum > 0 else "📉" if avg_momentum < 0 else "➡️"
        st.metric(
            f"{momentum_emoji} Avg Momentum",
            f"{avg_momentum:.1f}",
            delta="Global average"
        )
    
    # === TIME PERIOD INFO ===
    if overview.get('oldest_snapshot') and overview.get('newest_snapshot'):
        oldest = datetime.fromtimestamp(overview['oldest_snapshot'])
        newest = datetime.fromtimestamp(overview['newest_snapshot'])
        period_days = (newest - oldest).days
        
        st.info(f"📅 **Data Period:** {oldest.strftime('%Y-%m-%d %H:%M')} to {newest.strftime('%Y-%m-%d %H:%M')} ({period_days} days)")
    
    # === TABS FOR DIFFERENT ANALYSES ===
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🏆 Top Performers", 
        "📈 Trends Analysis", 
        "🔍 Token Deep Dive", 
        "⚡ Momentum Tracking",
        "📊 Comparative Analysis"
    ])
    
    with tab1:
        st.subheader("🏆 Top Performing Tokens")
        
        # Performance metric selector
        col1, col2 = st.columns([1, 3])
        
        with col1:
            metric_choice = st.selectbox(
                "Ranking by:",
                options=["viability_score", "momentum_score", "market_cap", "holder_count"],
                format_func=lambda x: {
                    "viability_score": "💪 Viability Score",
                    "momentum_score": "⚡ Momentum Score", 
                    "market_cap": "💰 Market Cap",
                    "holder_count": "👥 Holder Count"
                }[x]
            )
        
        # Get top performers
        top_performers = analyzer.get_top_performing_tokens(metric_choice, 20)
        
        if not top_performers.empty:
            with col2:
                # Top 10 chart
                top_10 = top_performers.head(10)
                
                fig_top = px.bar(
                    top_10,
                    x=metric_choice,
                    y='current_symbol',
                    orientation='h',
                    title=f"Top 10 by {metric_choice.replace('_', ' ').title()}",
                    color=metric_choice,
                    color_continuous_scale="Viridis"
                )
                fig_top.update_layout(height=400)
                st.plotly_chart(fig_top, use_container_width=True)
            
            # Detailed table
            st.markdown("**📋 Detailed Rankings**")
            
            display_performers = top_performers.copy()
            display_performers['token_display'] = display_performers['token_address'].apply(
                lambda x: f"{x[:8]}...{x[-8:]}"
            )
            display_performers['market_cap_formatted'] = display_performers['market_cap'].apply(format_large_number)
            display_performers['price_formatted'] = display_performers['price_usd'].apply(format_currency)
            display_performers['viability_formatted'] = display_performers['viability_score'].apply(lambda x: f"{x:.1f}")
            display_performers['risk_formatted'] = display_performers['risk_score'].apply(lambda x: f"{x:.1f}")
            display_performers['momentum_formatted'] = display_performers['momentum_score'].apply(lambda x: f"{x:.1f}")
            
            # Add link column for deep dive
            display_performers['🔍 Analyze'] = display_performers['token_address'].apply(
                lambda x: f"analyze_{x[:8]}"
            )
            
            selected_table = st.dataframe(
                display_performers[[
                    'token_display', 'current_symbol', 'current_name', 
                    'viability_formatted', 'risk_formatted', 'momentum_formatted',
                    'market_cap_formatted', 'price_formatted', 'holder_count'
                ]].rename(columns={
                    'token_display': 'Token',
                    'current_symbol': 'Symbol',
                    'current_name': 'Name',
                    'viability_formatted': 'Viability',
                    'risk_formatted': 'Risk',
                    'momentum_formatted': 'Momentum',
                    'market_cap_formatted': 'Market Cap',
                    'price_formatted': 'Price',
                    'holder_count': 'Holders'
                }),
                use_container_width=True,
                height=400,
                on_select="rerun",
                selection_mode="single-row"
            )
            
            # Handle selection for deep dive
            if selected_table.selection.rows and len(selected_table.selection.rows) > 0:
                selected_idx = selected_table.selection.rows[0]
                selected_token_addr = display_performers.iloc[selected_idx]['token_address']
                
                if st.button("🔍 Analyze Selected Token", type="primary"):
                    st.session_state.history_selected_token = selected_token_addr
                    st.session_state.history_active_tab = "🔍 Token Deep Dive"
                    st.rerun()
    
    with tab2:
        st.subheader("📈 Market Trends Analysis")
        
        # Time period selector
        col1, col2 = st.columns([1, 3])
        
        with col1:
            trend_days = st.selectbox(
                "Analysis Period:",
                options=[7, 14, 30, 90],
                format_func=lambda x: f"{x} days",
                index=1
            )
        
        # Get trends data
        trends_data = analyzer.get_score_trends_analysis(trend_days)
        
        if not trends_data.empty:
            with col2:
                # Multi-metric trends chart
                fig_trends = make_subplots(
                    rows=2, cols=2,
                    subplot_titles=('Average Scores Over Time', 'Token Activity', 'Market Metrics', 'Performance Distribution'),
                    specs=[[{"secondary_y": False}, {"secondary_y": False}],
                           [{"secondary_y": True}, {"secondary_y": False}]]
                )
                
                # Score trends
                fig_trends.add_trace(
                    go.Scatter(x=trends_data['snapshot_date'], y=trends_data['avg_viability'],
                              name='Viability', line=dict(color='green')),
                    row=1, col=1
                )
                fig_trends.add_trace(
                    go.Scatter(x=trends_data['snapshot_date'], y=trends_data['avg_risk'],
                              name='Risk', line=dict(color='red')),
                    row=1, col=1
                )
                fig_trends.add_trace(
                    go.Scatter(x=trends_data['snapshot_date'], y=trends_data['avg_momentum'],
                              name='Momentum', line=dict(color='blue')),
                    row=1, col=1
                )
                
                # Activity metrics
                fig_trends.add_trace(
                    go.Scatter(x=trends_data['snapshot_date'], y=trends_data['snapshot_count'],
                              name='Snapshots', line=dict(color='purple')),
                    row=1, col=2
                )
                fig_trends.add_trace(
                    go.Scatter(x=trends_data['snapshot_date'], y=trends_data['unique_tokens'],
                              name='Active Tokens', line=dict(color='orange')),
                    row=1, col=2
                )
                
                # Market metrics
                fig_trends.add_trace(
                    go.Scatter(x=trends_data['snapshot_date'], y=trends_data['avg_market_cap'],
                              name='Avg Market Cap', line=dict(color='darkgreen')),
                    row=2, col=1
                )
                fig_trends.add_trace(
                    go.Scatter(x=trends_data['snapshot_date'], y=trends_data['avg_volume_24h'],
                              name='Avg Volume', line=dict(color='darkblue')),
                    row=2, col=1, secondary_y=True
                )
                
                # Performance distribution
                fig_trends.add_trace(
                    go.Bar(x=trends_data['snapshot_date'], y=trends_data['high_performers'],
                           name='High Performers', marker_color='green'),
                    row=2, col=2
                )
                fig_trends.add_trace(
                    go.Bar(x=trends_data['snapshot_date'], y=trends_data['high_risk_count'],
                           name='High Risk', marker_color='red'),
                    row=2, col=2
                )
                
                fig_trends.update_layout(height=600, showlegend=True)
                st.plotly_chart(fig_trends, use_container_width=True)
            
            # Key insights
            st.markdown("**🔍 Key Insights**")
            
            latest_data = trends_data.iloc[0] if not trends_data.empty else {}
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if len(trends_data) >= 2:
                    viability_change = latest_data.get('avg_viability', 0) - trends_data.iloc[-1].get('avg_viability', 0)
                    emoji = "📈" if viability_change > 0 else "📉" if viability_change < 0 else "➡️"
                    st.metric(
                        "Viability Trend",
                        f"{latest_data.get('avg_viability', 0):.1f}",
                        delta=f"{viability_change:+.1f}"
                    )
            
            with col2:
                high_perf_ratio = (latest_data.get('high_performers', 0) / 
                                 max(latest_data.get('snapshot_count', 1), 1) * 100)
                st.metric(
                    "High Performers",
                    f"{high_perf_ratio:.1f}%",
                    delta=f"{latest_data.get('high_performers', 0)} tokens"
                )
            
            with col3:
                avg_market_cap = latest_data.get('avg_market_cap', 0)
                st.metric(
                    "Avg Market Cap",
                    format_large_number(avg_market_cap)
                )
    
    with tab3:
        st.subheader("🔍 Token Deep Dive Analysis")
        
        # Token selection
        if hasattr(st.session_state, 'history_selected_token') and st.session_state.history_selected_token:
            default_token = st.session_state.history_selected_token
        elif selected_token:
            default_token = selected_token
        else:
            default_token = tokens_with_history[0]['token_address'] if tokens_with_history else None
        
        if tokens_with_history:
            col1, col2 = st.columns([2, 1])
            
            with col1:
                token_options = {f"{token['token_address'][:8]}...{token['token_address'][-8:]} ({token['symbol'] or 'Unknown'})": token['token_address'] 
                               for token in tokens_with_history}
                
                selected_token_key = st.selectbox(
                    "Select Token for Analysis:",
                    options=list(token_options.keys()),
                    index=list(token_options.values()).index(default_token) if default_token in token_options.values() else 0
                )
                
                analyzed_token = token_options[selected_token_key]
            
            with col2:
                if st.button("🔄 Refresh Analysis", type="secondary"):
                    st.rerun()
            
            # Get detailed history
            history_data = analyzer.get_token_detailed_history(analyzed_token, 50)
            
            if not history_data.empty:
                # Token info
                latest_data = history_data.iloc[0]
                token_info = next((t for t in tokens_with_history if t['token_address'] == analyzed_token), {})
                
                st.markdown(f"**📋 Token:** `{analyzed_token}`")
                
                col1, col2, col3, col4, col5 = st.columns(5)
                
                with col1:
                    st.metric(
                        "📸 Snapshots",
                        len(history_data),
                        delta=f"From {datetime.fromtimestamp(token_info.get('first_snapshot', 0)).strftime('%m/%d')}"
                    )
                
                with col2:
                    st.metric(
                        "💪 Latest Viability",
                        f"{latest_data['viability_score']:.1f}",
                        delta=f"Risk: {latest_data['risk_score']:.1f}"
                    )
                
                with col3:
                    st.metric(
                        "⚡ Latest Momentum",
                        f"{latest_data['momentum_score']:.1f}",
                        delta="Current trend"
                    )
                
                with col4:
                    st.metric(
                        "💰 Market Cap",
                        format_large_number(latest_data['market_cap']),
                        delta=format_currency(latest_data['price_usd'])
                    )
                
                with col5:
                    st.metric(
                        "👥 Holders",
                        format_large_number(latest_data['holder_count']),
                        delta=f"Vol: {format_large_number(latest_data['volume_24h'])}"
                    )
                
                # Historical charts
                col1, col2 = st.columns(2)
                
                with col1:
                    # Score evolution
                    fig_scores = go.Figure()
                    
                    fig_scores.add_trace(go.Scatter(
                        x=history_data['snapshot_datetime'],
                        y=history_data['viability_score'],
                        mode='lines+markers',
                        name='Viability Score',
                        line=dict(color='green', width=2)
                    ))
                    
                    fig_scores.add_trace(go.Scatter(
                        x=history_data['snapshot_datetime'],
                        y=history_data['risk_score'],
                        mode='lines+markers',
                        name='Risk Score',
                        line=dict(color='red', width=2)
                    ))
                    
                    fig_scores.add_trace(go.Scatter(
                        x=history_data['snapshot_datetime'],
                        y=history_data['momentum_score'],
                        mode='lines+markers',
                        name='Momentum Score',
                        line=dict(color='blue', width=2)
                    ))
                    
                    fig_scores.update_layout(
                        title="📊 Score Evolution Over Time",
                        xaxis_title="Date",
                        yaxis_title="Score",
                        height=400
                    )
                    
                    st.plotly_chart(fig_scores, use_container_width=True)
                
                with col2:
                    # Market metrics evolution
                    fig_market = make_subplots(
                        rows=2, cols=1,
                        subplot_titles=('Price & Market Cap', 'Volume & Holders'),
                        specs=[[{"secondary_y": True}], [{"secondary_y": True}]]
                    )
                    
                    # Price and market cap
                    fig_market.add_trace(
                        go.Scatter(x=history_data['snapshot_datetime'], y=history_data['price_usd'],
                                  name='Price USD', line=dict(color='green')),
                        row=1, col=1
                    )
                    fig_market.add_trace(
                        go.Scatter(x=history_data['snapshot_datetime'], y=history_data['market_cap'],
                                  name='Market Cap', line=dict(color='blue')),
                        row=1, col=1, secondary_y=True
                    )
                    
                    # Volume and holders
                    fig_market.add_trace(
                        go.Scatter(x=history_data['snapshot_datetime'], y=history_data['volume_24h'],
                                  name='Volume 24h', line=dict(color='purple')),
                        row=2, col=1
                    )
                    fig_market.add_trace(
                        go.Scatter(x=history_data['snapshot_datetime'], y=history_data['holder_count'],
                                  name='Holders', line=dict(color='orange')),
                        row=2, col=1, secondary_y=True
                    )
                    
                    fig_market.update_layout(height=400, title="💰 Market Metrics Evolution")
                    fig_market.update_yaxes(title_text="Price USD", row=1, col=1)
                    fig_market.update_yaxes(title_text="Market Cap", row=1, col=1, secondary_y=True)
                    fig_market.update_yaxes(title_text="Volume 24h", row=2, col=1)
                    fig_market.update_yaxes(title_text="Holders", row=2, col=1, secondary_y=True)
                    
                    st.plotly_chart(fig_market, use_container_width=True)
                
                # Delta analysis
                st.markdown("**📈 Recent Changes Analysis**")
                
                # Filter recent deltas
                recent_deltas = history_data[history_data['price_delta_usd'] != 0].head(10)
                
                if not recent_deltas.empty:
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        # Price deltas chart
                        fig_deltas = px.bar(
                            recent_deltas,
                            x='snapshot_datetime',
                            y='price_delta_usd',
                            title="💲 Price Changes Over Time",
                            color='price_delta_usd',
                            color_continuous_scale='RdYlGn'
                        )
                        fig_deltas.update_layout(height=300)
                        st.plotly_chart(fig_deltas, use_container_width=True)
                    
                    with col2:
                        # Market cap deltas
                        fig_mc_deltas = px.bar(
                            recent_deltas,
                            x='snapshot_datetime',
                            y='market_cap_delta',
                            title="💰 Market Cap Changes",
                            color='market_cap_delta',
                            color_continuous_scale='RdYlGn'
                        )
                        fig_mc_deltas.update_layout(height=300)
                        st.plotly_chart(fig_mc_deltas, use_container_width=True)
                
                # Historical data table
                st.markdown("**📋 Historical Snapshots**")
                
                display_history = history_data.head(20).copy()
                display_history['snapshot_time'] = display_history['snapshot_datetime'].apply(
                    lambda x: pd.to_datetime(x).strftime('%m/%d %H:%M')
                )
                display_history['price_formatted'] = display_history['price_usd'].apply(format_currency)
                display_history['market_cap_formatted'] = display_history['market_cap'].apply(format_large_number)
                display_history['delta_formatted'] = display_history['price_delta_usd'].apply(
                    lambda x: f"+{x:.6f}" if x > 0 else f"{x:.6f}" if x < 0 else "0"
                )
                
                st.dataframe(
                    display_history[[
                        'snapshot_time', 'viability_score', 'risk_score', 'momentum_score',
                        'price_formatted', 'market_cap_formatted', 'holder_count', 'delta_formatted'
                    ]].rename(columns={
                        'snapshot_time': 'Time',
                        'viability_score': 'Viability',
                        'risk_score': 'Risk',
                        'momentum_score': 'Momentum',
                        'price_formatted': 'Price',
                        'market_cap_formatted': 'Market Cap',
                        'holder_count': 'Holders',
                        'delta_formatted': 'Price Δ'
                    }),
                    use_container_width=True,
                    height=400
                )
            
            else:
                st.warning("⚠️ No historical data found for this token")
        else:
            st.info("ℹ️ No tokens with historical data found")
    
    with tab4:
        st.subheader("⚡ Momentum Tracking")
        
        # Momentum analysis period
        col1, col2 = st.columns([1, 3])
        
        with col1:
            momentum_days = st.selectbox(
                "Analysis Period:",
                options=[3, 7, 14, 30],
                format_func=lambda x: f"{x} days",
                index=1,
                key="momentum_days"
            )
        
        # Get momentum data
        momentum_data = analyzer.get_momentum_analysis(momentum_days)
        
        if not momentum_data.empty:
            with col2:
                # Momentum distribution
                fig_momentum_dist = px.histogram(
                    momentum_data,
                    x='avg_momentum',
                    nbins=20,
                    title="📊 Momentum Score Distribution",
                    color_discrete_sequence=['lightblue']
                )
                fig_momentum_dist.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="Neutral")
                fig_momentum_dist.update_layout(height=300)
                st.plotly_chart(fig_momentum_dist, use_container_width=True)
            
            # Momentum categories
            st.markdown("**🔥 Momentum Categories**")
            
            col1, col2, col3, col4 = st.columns(4)
            
            strong_positive = len(momentum_data[momentum_data['avg_momentum'] > 50])
            positive = len(momentum_data[(momentum_data['avg_momentum'] > 0) & (momentum_data['avg_momentum'] <= 50)])
            negative = len(momentum_data[(momentum_data['avg_momentum'] < 0) & (momentum_data['avg_momentum'] >= -50)])
            strong_negative = len(momentum_data[momentum_data['avg_momentum'] < -50])
            
            with col1:
                st.metric("🚀 Strong Positive", strong_positive, delta="> +50")
            with col2:
                st.metric("📈 Positive", positive, delta="0 to +50")
            with col3:
                st.metric("📉 Negative", negative, delta="-50 to 0")
            with col4:
                st.metric("💥 Strong Negative", strong_negative, delta="< -50")
            
            # Top momentum gainers and losers
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**🏆 Top Momentum Gainers**")
                top_gainers = momentum_data.nlargest(10, 'avg_momentum')
                
                for i, (_, token) in enumerate(top_gainers.iterrows()):
                    momentum_val = token['avg_momentum']
                    color = get_score_color(momentum_val, "momentum")
                    
                    st.markdown(f"""
                    **{i+1}. {token['symbol'] or 'Unknown'}** ({token['token_address'][:8]}...)
                    - Momentum: **{momentum_val:.1f}** 
                    - Trend: {token['momentum_trend']:+.1f}
                    - Market Cap: {format_large_number(token['current_market_cap'])}
                    """)
            
            with col2:
                st.markdown("**📉 Biggest Momentum Losers**")
                top_losers = momentum_data.nsmallest(10, 'avg_momentum')
                
                for i, (_, token) in enumerate(top_losers.iterrows()):
                    momentum_val = token['avg_momentum']
                    
                    st.markdown(f"""
                    **{i+1}. {token['symbol'] or 'Unknown'}** ({token['token_address'][:8]}...)
                    - Momentum: **{momentum_val:.1f}**
                    - Trend: {token['momentum_trend']:+.1f}
                    - Market Cap: {format_large_number(token['current_market_cap'])}
                    """)
            
            # Momentum vs Viability scatter plot
            st.markdown("**📊 Momentum vs Viability Analysis**")
            
            fig_scatter = px.scatter(
                momentum_data,
                x='avg_momentum',
                y='avg_viability',
                size='current_market_cap',
                color='avg_momentum',
                hover_data=['symbol', 'token_address'],
                title="Momentum vs Viability Correlation",
                color_continuous_scale='RdYlGn',
                labels={
                    'avg_momentum': 'Average Momentum Score',
                    'avg_viability': 'Average Viability Score'
                }
            )
            
            # Add quadrant lines
            fig_scatter.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="Viability Threshold")
            fig_scatter.add_vline(x=0, line_dash="dash", line_color="gray", annotation_text="Momentum Neutral")
            
            fig_scatter.update_layout(height=500)
            st.plotly_chart(fig_scatter, use_container_width=True)
            
        else:
            st.info("ℹ️ No momentum data available for the selected period")
    
    with tab5:
        st.subheader("📊 Comparative Analysis")
        
        # Token selection for comparison
        st.markdown("**🔍 Select Tokens to Compare**")
        
        if tokens_with_history:
            token_options = {f"{token['symbol'] or 'Unknown'} ({token['token_address'][:8]}...)": token['token_address'] 
                           for token in tokens_with_history}
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                selected_tokens = st.multiselect(
                    "Choose tokens (max 5):",
                    options=list(token_options.keys()),
                    default=list(token_options.keys())[:3],
                    max_selections=5
                )
            
            with col2:
                comparison_days = st.selectbox(
                    "Comparison Period:",
                    options=[7, 14, 30],
                    format_func=lambda x: f"{x} days",
                    index=0,
                    key="comparison_days"
                )
            
            if selected_tokens:
                selected_addresses = [token_options[token] for token in selected_tokens]
                
                # Get comparison data
                comparison_data = analyzer.get_token_comparison_data(selected_addresses, comparison_days)
                
                if not comparison_data.empty:
                    # Comparison charts
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        # Score comparison over time
                        fig_comp_scores = go.Figure()
                        
                        for token_addr in selected_addresses:
                            token_data = comparison_data[comparison_data['token_address'] == token_addr]
                            token_symbol = token_data['symbol'].iloc[0] if not token_data.empty else token_addr[:8]
                            
                            fig_comp_scores.add_trace(go.Scatter(
                                x=token_data['snapshot_datetime'],
                                y=token_data['viability_score'],
                                mode='lines+markers',
                                name=f"{token_symbol} Viability",
                                line=dict(width=2)
                            ))
                        
                        fig_comp_scores.update_layout(
                            title="💪 Viability Score Comparison",
                            xaxis_title="Date",
                            yaxis_title="Viability Score",
                            height=400
                        )
                        st.plotly_chart(fig_comp_scores, use_container_width=True)
                    
                    with col2:
                        # Price comparison
                        fig_comp_price = go.Figure()
                        
                        for token_addr in selected_addresses:
                            token_data = comparison_data[comparison_data['token_address'] == token_addr]
                            token_symbol = token_data['symbol'].iloc[0] if not token_data.empty else token_addr[:8]
                            
                            # Normalize prices to percentage change from first value
                            if not token_data.empty:
                                first_price = token_data['price_usd'].iloc[-1]  # Last in time order (oldest)
                                if first_price > 0:
                                    normalized_prices = ((token_data['price_usd'] - first_price) / first_price * 100)
                                    
                                    fig_comp_price.add_trace(go.Scatter(
                                        x=token_data['snapshot_datetime'],
                                        y=normalized_prices,
                                        mode='lines+markers',
                                        name=f"{token_symbol} Price %",
                                        line=dict(width=2)
                                    ))
                        
                        fig_comp_price.add_hline(y=0, line_dash="dash", line_color="gray")
                        fig_comp_price.update_layout(
                            title="💲 Price Performance Comparison (%)",
                            xaxis_title="Date",
                            yaxis_title="Price Change (%)",
                            height=400
                        )
                        st.plotly_chart(fig_comp_price, use_container_width=True)
                    
                    # Comparison summary table
                    st.markdown("**📋 Comparison Summary**")
                    
                    summary_data = []
                    for token_addr in selected_addresses:
                        token_data = comparison_data[comparison_data['token_address'] == token_addr]
                        if not token_data.empty:
                            latest = token_data.iloc[0]  # Most recent
                            oldest = token_data.iloc[-1]  # Oldest in period
                            
                            price_change = ((latest['price_usd'] - oldest['price_usd']) / 
                                          max(oldest['price_usd'], 0.000001) * 100) if oldest['price_usd'] > 0 else 0
                            
                            summary_data.append({
                                'Token': f"{latest['symbol'] or 'Unknown'} ({token_addr[:8]}...)",
                                'Latest Viability': f"{latest['viability_score']:.1f}",
                                'Latest Risk': f"{latest['risk_score']:.1f}",
                                'Latest Momentum': f"{latest['momentum_score']:.1f}",
                                'Price Change %': f"{price_change:+.1f}%",
                                'Market Cap': format_large_number(latest['market_cap']),
                                'Holders': format_large_number(latest['holder_count'])
                            })
                    
                    if summary_data:
                        summary_df = pd.DataFrame(summary_data)
                        st.dataframe(summary_df, use_container_width=True)
                
                else:
                    st.warning("⚠️ No comparison data available for selected tokens and period")
            
            else:
                st.info("ℹ️ Please select tokens to compare")
        
        else:
            st.info("ℹ️ No tokens available for comparison")
    
    # === EXPORT FUNCTIONALITY ===
    st.subheader("📥 Data Export")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📊 Export Overview Data", type="secondary"):
            overview_df = pd.DataFrame([overview])
            csv_overview = overview_df.to_csv(index=False)
            
            st.download_button(
                label="💾 Download Overview (CSV)",
                data=csv_overview,
                file_name=f"token_history_overview_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )
    
    with col2:
        if tokens_with_history and st.button("🏆 Export Top Performers", type="secondary"):
            top_perf_export = analyzer.get_top_performing_tokens("viability_score", 50)
            if not top_perf_export.empty:
                csv_top_perf = top_perf_export.to_csv(index=False)
                
                st.download_button(
                    label="💾 Download Top Performers (CSV)",
                    data=csv_top_perf,
                    file_name=f"top_performers_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv"
                )
    
    with col3:
        if st.button("📈 Export Trends Data", type="secondary"):
            trends_export = analyzer.get_score_trends_analysis(30)
            if not trends_export.empty:
                csv_trends = trends_export.to_csv(index=False)
                
                st.download_button(
                    label="💾 Download Trends (CSV)",
                    data=csv_trends,
                    file_name=f"trends_analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv"
                )

def main():
    """Main function to test the module separately"""
    st.set_page_config(
        page_title="Token History Analytics",
        page_icon="📈",
        layout="wide"
    )
    
    st.title("📈 Token History Analytics Dashboard")
    
    # Database configuration
    db_path = st.sidebar.text_input(
        "Database path",
        value="solana_wallet_monitor.db"
    )
    
    # Initialize analyzer
    analyzer = TokenHistoryAnalyzer(db_path)
    
    if not analyzer.connect():
        st.error("Unable to connect to the database")
        st.stop()
    
    # Display dashboard
    display_token_history_analytics(analyzer)
    
    # Refresh button
    if st.sidebar.button("🔄 Refresh", type="primary"):
        st.rerun()

# Export main function for integration
__all__ = ['display_token_history_analytics', 'TokenHistoryAnalyzer']

if __name__ == "__main__":
    main()