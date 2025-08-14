import sqlite3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st
from datetime import datetime, timedelta
import numpy as np
from typing import Dict, List, Tuple, Optional

class TransactionAnalyzer:
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
    
    def get_transaction_overview(self) -> Dict:
        """Retrieves general transaction metrics"""
        if not self.conn:
            return {}
        
        query = """
        SELECT 
            COUNT(*) as total_transactions,
            COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as total_buys,
            COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as total_sells,
            COUNT(CASE WHEN transaction_type = 'TransactionType.TRANSFER_IN' THEN 1 END) as total_transfer_in,
            COUNT(CASE WHEN transaction_type = 'TransactionType.TRANSFER_OUT' THEN 1 END) as total_transfer_out,
            COUNT(DISTINCT wallet_address) as unique_wallets,
            COUNT(DISTINCT token_mint) as unique_tokens,
            SUM(amount) as total_volume_sol,
            AVG(amount) as avg_amount_sol,
            AVG(detection_delay) as avg_detection_delay,
            AVG(wallet_priority_at_detection) as avg_wallet_priority,
            MIN(created_at) as first_transaction_time,
            MAX(created_at) as last_transaction_time,
            
            -- Recent activity (24h)
            COUNT(CASE WHEN created_at >= strftime('%s', 'now') - 86400 THEN 1 END) as transactions_24h,
            COUNT(CASE WHEN created_at >= strftime('%s', 'now') - 86400 AND transaction_type = 'TransactionType.BUY' THEN 1 END) as buys_24h,
            COUNT(CASE WHEN created_at >= strftime('%s', 'now') - 86400 AND transaction_type = 'TransactionType.SELL' THEN 1 END) as sells_24h,
            
            -- Recent activity (1h)
            COUNT(CASE WHEN created_at >= strftime('%s', 'now') - 3600 THEN 1 END) as transactions_1h,
            COUNT(CASE WHEN created_at >= strftime('%s', 'now') - 3600 AND transaction_type = 'TransactionType.BUY' THEN 1 END) as buys_1h,
            COUNT(CASE WHEN created_at >= strftime('%s', 'now') - 3600 AND transaction_type = 'TransactionType.SELL' THEN 1 END) as sells_1h,
            
            -- Recent activity (5min)
            COUNT(CASE WHEN created_at >= strftime('%s', 'now') - 300 THEN 1 END) as transactions_5m,
            COUNT(CASE WHEN created_at >= strftime('%s', 'now') - 300 AND transaction_type = 'TransactionType.BUY' THEN 1 END) as buys_5m,
            COUNT(CASE WHEN created_at >= strftime('%s', 'now') - 300 AND transaction_type = 'TransactionType.SELL' THEN 1 END) as sells_5m,
            
            -- Recent volume
            SUM(CASE WHEN created_at >= strftime('%s', 'now') - 86400 THEN amount ELSE 0 END) as volume_24h,
            SUM(CASE WHEN created_at >= strftime('%s', 'now') - 3600 THEN amount ELSE 0 END) as volume_1h,
            
            -- Recent active tokens
            COUNT(DISTINCT CASE WHEN created_at >= strftime('%s', 'now') - 86400 THEN token_mint END) as active_tokens_24h,
            COUNT(DISTINCT CASE WHEN created_at >= strftime('%s', 'now') - 3600 THEN token_mint END) as active_tokens_1h
            
        FROM transactions
        WHERE created_at IS NOT NULL;
        """
        
        result = pd.read_sql_query(query, self.conn)
        return result.iloc[0].to_dict() if len(result) > 0 else {}
    
    def get_scanner_performance_metrics(self) -> Dict:
        """Analyzes scanner performance"""
        if not self.conn:
            return {}
        
        # First query for basic metrics
        query_basic = """
        SELECT 
            COUNT(DISTINCT scan_cycle_id) as total_scan_cycles,
            AVG(detection_delay) as avg_detection_delay,
            MIN(detection_delay) as min_detection_delay,
            MAX(detection_delay) as max_detection_delay,
            COUNT(*) as total_detections,
            
            -- Detection speed by category
            COUNT(CASE WHEN detection_delay <= 5 THEN 1 END) as ultra_fast_detections,
            COUNT(CASE WHEN detection_delay > 5 AND detection_delay <= 30 THEN 1 END) as fast_detections,
            COUNT(CASE WHEN detection_delay > 30 AND detection_delay <= 120 THEN 1 END) as normal_detections,
            COUNT(CASE WHEN detection_delay > 120 THEN 1 END) as slow_dictions,
            
            -- Quality of detected wallets
            AVG(wallet_priority_at_detection) as avg_wallet_quality,
            COUNT(CASE WHEN wallet_priority_at_detection >= 0.8 THEN 1 END) as high_priority_wallets,
            COUNT(CASE WHEN wallet_priority_at_detection >= 0.5 AND wallet_priority_at_detection < 0.8 THEN 1 END) as medium_priority_wallets,
            COUNT(CASE WHEN wallet_priority_at_detection < 0.5 THEN 1 END) as low_priority_wallets,
            
            -- Source analysis
            COUNT(DISTINCT source) as unique_sources
            
        FROM transactions
        WHERE detection_delay IS NOT NULL
        """
        
        result = pd.read_sql_query(query_basic, self.conn)
        metrics = result.iloc[0].to_dict() if len(result) > 0 else {}
        
        # Manual calculation of percentiles with pandas
        if metrics.get('total_detections', 0) > 0:
            delay_query = """
            SELECT detection_delay
            FROM transactions
            WHERE detection_delay IS NOT NULL
            ORDER BY detection_delay
            """
            delays_df = pd.read_sql_query(delay_query, self.conn)
            
            if not delays_df.empty:
                metrics['median_detection_delay'] = delays_df['detection_delay'].median()
                metrics['p95_detection_delay'] = delays_df['detection_delay'].quantile(0.95)
            else:
                metrics['median_detection_delay'] = 0
                metrics['p95_detection_delay'] = 0
        else:
            metrics['median_detection_delay'] = 0
            metrics['p95_detection_delay'] = 0
        
        return metrics
    
    def get_hourly_activity_trends(self, hours: int = 24) -> pd.DataFrame:
        """Retrieves hourly activity trends"""
        if not self.conn:
            return pd.DataFrame()
        
        current_timestamp = datetime.now().timestamp()
        start_timestamp = current_timestamp - (hours * 3600)
        
        query = """
        SELECT 
            datetime(block_time, 'unixepoch') as hour_timestamp,
            strftime('%H', datetime(block_time, 'unixepoch')) as hour,
            COUNT(*) as total_transactions,
            COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as buys,
            COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as sells,
            COUNT(CASE WHEN transaction_type = 'TransactionType.TRANSFER_IN' THEN 1 END) as transfers_in,
            COUNT(CASE WHEN transaction_type = 'TransactionType.TRANSFER_OUT' THEN 1 END) as transfers_out,
            SUM(amount) as volume,
            COUNT(DISTINCT wallet_address) as unique_wallets,
            COUNT(DISTINCT token_mint) as unique_tokens,
            AVG(detection_delay) as avg_detection_delay,
            AVG(wallet_priority_at_detection) as avg_wallet_priority
        FROM transactions
        WHERE block_time >= ?
        GROUP BY strftime('%Y-%m-%d %H', datetime(block_time, 'unixepoch'))
        ORDER BY hour_timestamp DESC
        """
        
        return pd.read_sql_query(query, self.conn, params=[start_timestamp])
    
    def get_token_activity_ranking(self, limit: int = 20) -> pd.DataFrame:
        """Ranking of the most active tokens"""
        if not self.conn:
            return pd.DataFrame()
        
        current_timestamp = datetime.now().timestamp()
        
        query = """
        SELECT 
            token_mint,
            token_symbol,
            token_name,
            COUNT(*) as total_transactions,
            COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as buys,
            COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as sells,
            COUNT(DISTINCT wallet_address) as unique_wallets,
            SUM(amount) as total_volume,
            AVG(detection_delay) as avg_detection_delay,
            AVG(wallet_priority_at_detection) as avg_wallet_priority,
            
            -- Recent activity
            COUNT(CASE WHEN block_time >= ? - 86400 THEN 1 END) as transactions_24h,
            COUNT(CASE WHEN block_time >= ? - 3600 THEN 1 END) as transactions_1h,
            
            -- Activity score
            (COUNT(CASE WHEN block_time >= ? - 86400 THEN 1 END) * 1.0 + 
             COUNT(DISTINCT wallet_address) * 2.0 + 
             AVG(wallet_priority_at_detection) * 10.0) as activity_score
             
        FROM transactions
        WHERE token_mint IS NOT NULL 
        AND token_mint != ''
        GROUP BY token_mint
        HAVING total_transactions >= 5
        ORDER BY activity_score DESC
        LIMIT ?
        """
        
        params = [current_timestamp, current_timestamp, current_timestamp, limit]
        return pd.read_sql_query(query, self.conn, params=params)
    
    def get_wallet_activity_ranking(self, limit: int = 20) -> pd.DataFrame:
        """Ranking of the most active wallets"""
        if not self.conn:
            return pd.DataFrame()
        
        current_timestamp = datetime.now().timestamp()
        
        query = """
        SELECT 
            wallet_address,
            COUNT(*) as total_transactions,
            COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as buys,
            COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as sells,
            COUNT(CASE WHEN transaction_type = 'TransactionType.TRANSFER_IN' THEN 1 END) as transfers_in,
            COUNT(CASE WHEN transaction_type = 'TransactionType.TRANSFER_OUT' THEN 1 END) as transfers_out,
            COUNT(DISTINCT token_mint) as unique_tokens,
            SUM(amount) as total_volume,
            AVG(detection_delay) as avg_detection_delay,
            AVG(wallet_priority_at_detection) as avg_wallet_priority,
            
            -- Recent activity
            COUNT(CASE WHEN block_time >= ? - 86400 THEN 1 END) as transactions_24h,
            COUNT(CASE WHEN block_time >= ? - 3600 THEN 1 END) as transactions_1h,
            
            -- Last activity
            MAX(block_time) as last_activity_timestamp
            
        FROM transactions
        WHERE wallet_address IS NOT NULL
        GROUP BY wallet_address
        HAVING total_transactions >= 3
        ORDER BY transactions_24h DESC, total_transactions DESC
        LIMIT ?
        """
        
        params = [current_timestamp, current_timestamp, limit]
        return pd.read_sql_query(query, self.conn, params=params)
    
    def get_detection_delay_analysis(self) -> pd.DataFrame:
        """Detailed analysis of detection delays"""
        if not self.conn:
            return pd.DataFrame()
        
        query = """
        SELECT 
            CASE 
                WHEN detection_delay <= 5 THEN '⚡ Ultra-Fast (≤5s)'
                WHEN detection_delay <= 30 THEN '🚀 Fast (≤30s)'
                WHEN detection_delay <= 120 THEN '🟢 Normal (≤2min)'
                WHEN detection_delay <= 600 THEN '🟡 Slow (≤10min)'
                ELSE '🔴 Very Slow (>10min)'
            END as speed_category,
            COUNT(*) as transaction_count,
            AVG(detection_delay) as avg_delay,
            MIN(detection_delay) as min_delay,
            MAX(detection_delay) as max_delay,
            AVG(wallet_priority_at_detection) as avg_wallet_priority,
            
            -- Breakdown by transaction type
            COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as buys,
            COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as sells
            
        FROM transactions
        WHERE detection_delay IS NOT NULL
        GROUP BY 
            CASE 
                WHEN detection_delay <= 5 THEN '⚡ Ultra-Fast (≤5s)'
                WHEN detection_delay <= 30 THEN '🚀 Fast (≤30s)'
                WHEN detection_delay <= 120 THEN '🟢 Normal (≤2min)'
                WHEN detection_delay <= 600 THEN '🟡 Slow (≤10min)'
                ELSE '🔴 Very Slow (>10min)'
            END
        ORDER BY avg_delay
        """
        
        return pd.read_sql_query(query, self.conn)

def format_number(num: float) -> str:
    """Formats numbers for display"""
    if num is None or pd.isna(num):
        return "N/A"
    
    if num >= 1000000:
        return f"{num/1000000:.2f}M"
    elif num >= 1000:
        return f"{num/1000:.2f}K"
    else:
        return f"{num:,.0f}"

def format_duration_seconds(seconds: float) -> str:
    """Formats duration in seconds"""
    if seconds is None or pd.isna(seconds):
        return "N/A"
    
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}min"
    else:
        return f"{seconds/3600:.1f}h"

def get_activity_status(transactions_5m: int, transactions_1h: int) -> Tuple[str, str]:
    """Determines scanner activity status"""
    if transactions_5m > 0:
        return "🟢", "ACTIVE (transactions detected in the last 5 minutes)"
    elif transactions_1h > 0:
        return "🟡", "MODERATE (transactions detected in the last hour)"
    else:
        return "🔴", "INACTIVE (no recent transactions detected)"

def display_transaction_analytics(analyzer: TransactionAnalyzer):
    """Displays the transaction analysis dashboard"""
    
    st.header("🔄 Transaction Analytics - Scanner Performance")
    st.markdown("*Real-time monitoring of scanner activity and transaction analysis*")
    
    # === GENERAL METRICS ===
    with st.spinner("📊 Loading metrics..."):
        overview = analyzer.get_transaction_overview()
        scanner_metrics = analyzer.get_scanner_performance_metrics()
    
    if not overview:
        st.error("❌ No transaction data found")
        return
    
    # Scanner status
    status_emoji, status_text = get_activity_status(
        overview.get('transactions_5m', 0),
        overview.get('transactions_1h', 0)
    )
    
    st.subheader(f"{status_emoji} Scanner Status")
    st.info(f"**{status_text}**")
    
    # === REAL-TIME METRICS ===
    st.subheader("⚡ Real-Time Activity")
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        st.metric(
            "🔄 5 Minutes",
            overview.get('transactions_5m', 0),
            delta=f"🛒 {overview.get('buys_5m', 0)} | 🏪 {overview.get('sells_5m', 0)}"
        )
    
    with col2:
        st.metric(
            "🕐 1 Hour", 
            overview.get('transactions_1h', 0),
            delta=f"🛒 {overview.get('buys_1h', 0)} | 🏪 {overview.get('sells_1h', 0)}"
        )
    
    with col3:
        st.metric(
            "📅 24 Hours",
            overview.get('transactions_24h', 0),
            delta=f"🛒 {overview.get('buys_24h', 0)} | 🏪 {overview.get('sells_24h', 0)}"
        )
    
    with col4:
        volume_1h = overview.get('volume_1h', 0)
        st.metric(
            "💰 1h Volume",
            f"{volume_1h:.2f} SOL" if volume_1h else "0 SOL"
        )
    
    with col5:
        st.metric(
            "🪙 Active Tokens 1h",
            overview.get('active_tokens_1h', 0)
        )
    
    with col6:
        if overview.get('last_transaction_time'):
            last_tx_time = datetime.fromtimestamp(overview['last_transaction_time'])
            time_diff = datetime.now() - last_tx_time
            
            if time_diff.total_seconds() < 300:  # 5 minutes
                delta_color = "normal"
                delta_text = f"{int(time_diff.total_seconds())}s ago"
            elif time_diff.total_seconds() < 3600:  # 1 hour
                delta_color = "inverse"
                delta_text = f"{int(time_diff.total_seconds()/60)}min ago"
            else:
                delta_color = "off"
                delta_text = f"{int(time_diff.total_seconds()/3600)}h ago"
            
            st.metric(
                "🕰️ Last TX",
                last_tx_time.strftime('%H:%M:%S'),
                delta=delta_text
            )
    
    # === GLOBAL METRICS ===
    st.subheader("📊 Global Overview")
    
    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
    
    with col1:
        st.metric("📈 Total TX", format_number(overview.get('total_transactions', 0)))
    
    with col2:
        buys = overview.get('total_buys', 0)
        sells = overview.get('total_sells', 0)
        buy_ratio = (buys / (buys + sells) * 100) if (buys + sells) > 0 else 0
        st.metric(
            "🛒 Buys",
            format_number(buys),
            delta=f"{buy_ratio:.1f}% of total"
        )
    
    with col3:
        st.metric(
            "🏪 Sells", 
            format_number(sells),
            delta=f"{100-buy_ratio:.1f}% of total"
        )
    
    with col4:
        transfer_in = overview.get('total_transfer_in', 0)
        transfer_out = overview.get('total_transfer_out', 0)
        st.metric(
            "📥 Transfers IN",
            format_number(transfer_in),
            delta=f"📤 {format_number(transfer_out)} OUT"
        )
    
    with col5:
        st.metric("👥 Unique Wallets", format_number(overview.get('unique_wallets', 0)))
    
    with col6:
        st.metric("🪙 Unique Tokens", format_number(overview.get('unique_tokens', 0)))
    
    with col7:
        total_volume = overview.get('total_volume_sol', 0)
        st.metric("💰 Total Volume", f"{total_volume:.2f} SOL" if total_volume else "0 SOL")
    
    # === SCANNER PERFORMANCE ===
    st.subheader("🎯 Scanner Performance")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        avg_delay = scanner_metrics.get('avg_detection_delay', 0)
        st.metric(
            "⏱️ Average Delay",
            format_duration_seconds(avg_delay),
            delta=f"Min: {format_duration_seconds(scanner_metrics.get('min_detection_delay', 0))}"
        )
    
    with col2:
        st.metric(
            "📊 Median",
            format_duration_seconds(scanner_metrics.get('median_detection_delay', 0)),
            delta=f"P95: {format_duration_seconds(scanner_metrics.get('p95_detection_delay', 0))}"
        )
    
    with col3:
        ultra_fast = scanner_metrics.get('ultra_fast_detections', 0)
        total_detections = (ultra_fast + 
                          scanner_metrics.get('fast_detections', 0) + 
                          scanner_metrics.get('normal_detections', 0) + 
                          scanner_metrics.get('slow_detections', 0))
        ultra_fast_pct = (ultra_fast / total_detections * 100) if total_detections > 0 else 0
        
        st.metric(
            "⚡ Ultra-Fast",
            format_number(ultra_fast),
            delta=f"{ultra_fast_pct:.1f}% (≤5s)"
        )
    
    with col4:
        avg_wallet_quality = scanner_metrics.get('avg_wallet_quality', 0)
        st.metric(
            "🧠 Wallet Quality",
            f"{avg_wallet_quality:.3f}" if avg_wallet_quality else "N/A",
            delta="Average priority score"
        )
    
    with col5:
        high_priority = scanner_metrics.get('high_priority_wallets', 0)
        st.metric(
            "🎯 Premium Wallets",
            format_number(high_priority),
            delta="Priority ≥ 0.8"
        )
    
    # === ANALYSIS CHARTS ===
    st.subheader("📈 Temporal Analysis")
    
    # Hourly trends
    with st.spinner("📊 Generating charts..."):
        hourly_data = analyzer.get_hourly_activity_trends(24)
    
    if not hourly_data.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            # Hourly activity chart
            fig_hourly = go.Figure()
            
            fig_hourly.add_trace(go.Scatter(
                x=hourly_data['hour_timestamp'],
                y=hourly_data['total_transactions'],
                mode='lines+markers',
                name='Total TX',
                line=dict(color='blue', width=2)
            ))
            
            fig_hourly.add_trace(go.Scatter(
                x=hourly_data['hour_timestamp'],
                y=hourly_data['buys'],
                mode='lines+markers',
                name='Buys',
                line=dict(color='green', width=2)
            ))
            
            fig_hourly.add_trace(go.Scatter(
                x=hourly_data['hour_timestamp'],
                y=hourly_data['sells'],
                mode='lines+markers',
                name='Sells',
                line=dict(color='red', width=2)
            ))
            
            fig_hourly.update_layout(
                title="📊 Transaction Activity by Hour",
                xaxis_title="Hour",
                yaxis_title="Number of Transactions",
                height=400,
                hovermode='x unified'
            )
            
            st.plotly_chart(fig_hourly, use_container_width=True)
        
        with col2:
            # Volume and detection delay
            fig_metrics = make_subplots(
                rows=2, cols=1,
                subplot_titles=('Hourly SOL Volume', 'Average Detection Delay'),
                vertical_spacing=0.15
            )
            
            fig_metrics.add_trace(
                go.Scatter(
                    x=hourly_data['hour_timestamp'],
                    y=hourly_data['volume'],
                    mode='lines+markers',
                    name='SOL Volume',
                    line=dict(color='purple', width=2)
                ),
                row=1, col=1
            )
            
            fig_metrics.add_trace(
                go.Scatter(
                    x=hourly_data['hour_timestamp'],
                    y=hourly_data['avg_detection_delay'],
                    mode='lines+markers',
                    name='Detection Delay',
                    line=dict(color='orange', width=2)
                ),
                row=2, col=1
            )
            
            fig_metrics.update_layout(height=400, showlegend=False)
            fig_metrics.update_xaxes(title_text="Hour", row=2, col=1)
            fig_metrics.update_yaxes(title_text="Volume (SOL)", row=1, col=1)
            fig_metrics.update_yaxes(title_text="Delay (seconds)", row=2, col=1)
            
            st.plotly_chart(fig_metrics, use_container_width=True)
    
    # === DETECTION DELAY ANALYSIS ===
    st.subheader("⚡ Detection Delay Analysis")
    
    detection_analysis = analyzer.get_detection_delay_analysis()
    
    if not detection_analysis.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            # Pie chart of speed categories
            fig_pie = px.pie(
                detection_analysis,
                values='transaction_count',
                names='speed_category',
                title="Distribution of Detection Speeds",
                color_discrete_map={
                    '⚡ Ultra-Fast (≤5s)': 'darkgreen',
                    '🚀 Fast (≤30s)': 'green',
                    '🟢 Normal (≤2min)': 'lightgreen',
                    '🟡 Slow (≤10min)': 'orange',
                    '🔴 Very Slow (>10min)': 'red'
                }
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with col2:
            # Detailed performance table
            st.markdown("**📋 Performance Details by Category**")
            
            display_detection = detection_analysis.copy()
            display_detection['avg_delay_formatted'] = display_detection['avg_delay'].apply(format_duration_seconds)
            display_detection['transaction_count_formatted'] = display_detection['transaction_count'].apply(format_number)
            display_detection['avg_wallet_priority_formatted'] = display_detection['avg_wallet_priority'].apply(lambda x: f"{x:.3f}" if x else "N/A")
            
            st.dataframe(
                display_detection[['speed_category', 'transaction_count_formatted', 'avg_delay_formatted', 'avg_wallet_priority_formatted', 'buys', 'sells']].rename(columns={
                    'speed_category': 'Category',
                    'transaction_count_formatted': 'Transactions',
                    'avg_delay_formatted': 'Average Delay',
                    'avg_wallet_priority_formatted': 'Average Priority',
                    'buys': 'Buys',
                    'sells': 'Sells'
                }),
                use_container_width=True,
                height=250
            )
    
    # === RANKINGS ===
    st.subheader("🏆 Activity Rankings")
    
    tab1, tab2 = st.tabs(["🪙 Most Active Tokens", "👥 Most Active Wallets"])
    
    with tab1:
        token_ranking = analyzer.get_token_activity_ranking(20)
        
        if not token_ranking.empty:
            col1, col2 = st.columns([2, 1])
            
            with col1:
                # Token table
                display_tokens = token_ranking.copy()
                display_tokens['token_display'] = display_tokens['token_mint'].apply(lambda x: f"{x[:8]}...{x[-8:]}" if x else "N/A")
                display_tokens['volume_formatted'] = display_tokens['total_volume'].apply(lambda x: f"{x:.2f}" if x else "0")
                display_tokens['delay_formatted'] = display_tokens['avg_detection_delay'].apply(format_duration_seconds)
                display_tokens['priority_formatted'] = display_tokens['avg_wallet_priority'].apply(lambda x: f"{x:.3f}" if x else "N/A")
                
                st.dataframe(
                    display_tokens[['token_display', 'token_symbol', 'total_transactions', 'buys', 'sells', 'unique_wallets', 'volume_formatted', 'transactions_24h', 'delay_formatted', 'priority_formatted']].rename(columns={
                        'token_display': 'Token',
                        'token_symbol': 'Symbol',
                        'total_transactions': 'Total TX',
                        'buys': 'Buys',
                        'sells': 'Sells',
                        'unique_wallets': 'Wallets',
                        'volume_formatted': 'SOL Volume',
                        'transactions_24h': 'TX 24h',
                        'delay_formatted': 'Avg. Delay',
                        'priority_formatted': 'Priority'
                    }),
                    use_container_width=True,
                    height=400
                )
            
            with col2:
                # Top 10 tokens by recent activity
                top_active = token_ranking.head(10)
                
                fig_tokens = px.bar(
                    top_active,
                    x='transactions_24h',
                    y='token_symbol',
                    orientation='h',
                    title="🔥 Top 10 - 24h Activity",
                    labels={'transactions_24h': 'Transactions 24h', 'token_symbol': 'Token'}
                )
                fig_tokens.update_layout(height=400)
                st.plotly_chart(fig_tokens, use_container_width=True)
    
    with tab2:
        wallet_ranking = analyzer.get_wallet_activity_ranking(20)
        
        if not wallet_ranking.empty:
            col1, col2 = st.columns([2, 1])
            
            with col1:
                # Wallet table
                display_wallets = wallet_ranking.copy()
                display_wallets['wallet_display'] = display_wallets['wallet_address'].apply(lambda x: f"{x[:8]}...{x[-8:]}" if x else "N/A")
                display_wallets['volume_formatted'] = display_wallets['total_volume'].apply(lambda x: f"{x:.2f}" if x else "0")
                display_wallets['delay_formatted'] = display_wallets['avg_detection_delay'].apply(format_duration_seconds)
                display_wallets['priority_formatted'] = display_wallets['avg_wallet_priority'].apply(lambda x: f"{x:.3f}" if x else "N/A")
                
                # Last activity
                display_wallets['last_activity_formatted'] = display_wallets['last_activity_timestamp'].apply(
                    lambda x: datetime.fromtimestamp(x).strftime('%H:%M:%S') if x else "N/A"
                )
                
                st.dataframe(
                    display_wallets[['wallet_display', 'total_transactions', 'buys', 'sells', 'transfers_in', 'transfers_out', 'unique_tokens', 'volume_formatted', 'transactions_24h', 'priority_formatted', 'last_activity_formatted']].rename(columns={
                        'wallet_display': 'Wallet',
                        'total_transactions': 'Total TX',
                        'buys': 'Buys',
                        'sells': 'Sells',
                        'transfers_in': 'Transfer IN',
                        'transfers_out': 'Transfer OUT',
                        'unique_tokens': 'Tokens',
                        'volume_formatted': 'SOL Volume',
                        'transactions_24h': 'TX 24h',
                        'priority_formatted': 'Priority',
                        'last_activity_formatted': 'Last Activity'
                    }),
                    use_container_width=True,
                    height=400
                )
            
            with col2:
                # Transaction type distribution for active wallets
                wallet_tx_types = pd.DataFrame({
                    'Type': ['Buys', 'Sells', 'Transfer IN', 'Transfer OUT'],
                    'Total': [
                        wallet_ranking['buys'].sum(),
                        wallet_ranking['sells'].sum(),
                        wallet_ranking['transfers_in'].sum(),
                        wallet_ranking['transfers_out'].sum()
                    ]
                })
                
                fig_wallet_types = px.pie(
                    wallet_tx_types,
                    values='Total',
                    names='Type',
                    title="TX Type Distribution",
                    color_discrete_map={
                        'Buys': 'green',
                        'Sells': 'red',
                        'Transfer IN': 'blue',
                        'Transfer OUT': 'orange'
                    }
                )
                fig_wallet_types.update_layout(height=400)
                st.plotly_chart(fig_wallet_types, use_container_width=True)
    
    # === ALERTS AND RECOMMENDATIONS ===
    st.subheader("🚨 Alerts and Recommendations")
    
    # Calculation of alerts based on metrics
    alerts = []
    recommendations = []
    
    # Checking recent activity
    if overview.get('transactions_5m', 0) == 0:
        if overview.get('transactions_1h', 0) == 0:
            alerts.append("🔴 **CRITICAL ALERT:** No transactions detected in the last hour")
            recommendations.append("Check scanner status and blockchain connectivity")
        else:
            alerts.append("🟡 **WARNING:** No transactions in the last 5 minutes")
            recommendations.append("Monitor scanner activity")
    
    # Checking detection delays
    avg_delay = scanner_metrics.get('avg_detection_delay', 0)
    if avg_delay > 120:  # More than 2 minutes
        alerts.append(f"🟠 **PERFORMANCE:** High detection delay ({format_duration_seconds(avg_delay)})")
        recommendations.append("Optimize scanner performance or check system load")
    
    # Checking buy/sell ratio
    total_buys = overview.get('total_buys', 0)
    total_sells = overview.get('total_sells', 0)
    if total_sells > 0:
        buy_sell_ratio = total_buys / total_sells
        if buy_sell_ratio < 0.3:  # Significantly more sells
            alerts.append("📉 **MARKET:** Strong sell dominance detected")
            recommendations.append("Analyze market conditions and adjust strategies")
    
    # Checking wallet quality
    avg_wallet_quality = scanner_metrics.get('avg_wallet_quality', 0)
    if avg_wallet_quality < 0.3:
        alerts.append("🎯 **QUALITY:** Low wallet priority score")
        recommendations.append("Review wallet selection criteria for monitoring")
    
    # Display alerts
    if alerts:
        for alert in alerts:
            st.warning(alert)
    else:
        st.success("✅ **STATUS:** All indicators are normal")
    
    # Display recommendations
    if recommendations:
        st.markdown("**💡 Recommendations:**")
        for i, rec in enumerate(recommendations, 1):
            st.markdown(f"{i}. {rec}")
    
    # === DATA EXPORT ===
    st.subheader("📥 Data Export")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📊 Export Global Metrics", type="secondary"):
            # Prepare export data
            export_overview = pd.DataFrame([overview])
            csv_overview = export_overview.to_csv(index=False)
            
            st.download_button(
                label="💾 Download Metrics (CSV)",
                data=csv_overview,
                file_name=f"transaction_metrics_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )
    
    with col2:
        if not hourly_data.empty and st.button("📈 Export Hourly Data", type="secondary"):
            csv_hourly = hourly_data.to_csv(index=False)
            
            st.download_button(
                label="💾 Download Hourly (CSV)",
                data=csv_hourly,
                file_name=f"hourly_activity_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )
    
    with col3:
        if not token_ranking.empty and st.button("🏆 Export Rankings", type="secondary"):
            # Combine token and wallet rankings
            combined_export = {
                'tokens': token_ranking,
                'wallets': wallet_ranking
            }
            
            # Export token ranking
            csv_tokens = token_ranking.to_csv(index=False)
            
            st.download_button(
                label="💾 Download Rankings (CSV)",
                data=csv_tokens,
                file_name=f"activity_rankings_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )
    
    # === TECHNICAL INFORMATION ===
    with st.expander("🔧 Technical Information"):
        st.markdown("**📋 Database Details:**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if overview.get('first_transaction_time'):
                first_tx = datetime.fromtimestamp(overview['first_transaction_time'])
                st.write(f"🎯 **First transaction:** {first_tx.strftime('%Y-%m-%d %H:%M:%S')}")
            
            if overview.get('last_transaction_time'):
                last_tx = datetime.fromtimestamp(overview['last_transaction_time'])
                st.write(f"🕐 **Last transaction:** {last_tx.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Calculate data period
            data_period_hours = None
            if overview.get('first_transaction_time') and overview.get('last_transaction_time'):
                data_period = overview['last_transaction_time'] - overview['first_transaction_time']
                data_period_hours = data_period / 3600
                st.write(f"📊 **Data period:** {format_duration_seconds(data_period)}")

        with col2:
            st.write(f"🔄 **Unique scan cycles:** {scanner_metrics.get('total_scan_cycles', 'N/A')}")
            st.write(f"📡 **Unique sources:** {scanner_metrics.get('unique_sources', 'N/A')}")
            
            # Transaction rate per hour
            if data_period_hours and data_period_hours > 0:
                tx_per_hour = overview.get('total_transactions', 0) / data_period_hours
                st.write(f"📈 **Average rate:** {tx_per_hour:.1f} TX/hour")
        
        # Transaction rate per hour
        if data_period_hours and data_period_hours > 0:
            tx_per_hour = overview.get('total_transactions', 0) / data_period_hours
            st.write(f"📈 **Average rate:** {tx_per_hour:.1f} TX/hour")

def main():
    """Main function to test the module separately"""
    st.set_page_config(
        page_title="Transaction Analytics",
        page_icon="🔄",
        layout="wide"
    )
    
    st.title("🔄 Transaction Analytics Dashboard")
    
    # Database configuration
    db_path = st.sidebar.text_input(
        "Database path",
        value="solana_wallet_monitor.db"
    )
    
    # Initialize analyzer
    analyzer = TransactionAnalyzer(db_path)
    
    if not analyzer.connect():
        st.error("Unable to connect to the database")
        st.stop()
    
    # Display dashboard
    display_transaction_analytics(analyzer)
    
    # Refresh button
    if st.sidebar.button("🔄 Refresh", type="primary"):
        st.rerun()

# Export main function for integration
__all__ = ['display_transaction_analytics', 'TransactionAnalyzer']

if __name__ == "__main__":
    main()