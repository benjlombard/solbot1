import sqlite3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st
from datetime import datetime, timedelta
import numpy as np
import requests
import json
import time
from typing import Dict, Optional

# Streamlit page configuration
st.set_page_config(
    page_title="Token Analysis - Dashboard",
    page_icon="🪙",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.scroll-top-btn {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background-color: #ff4b4b;
    color: white;
    border: none;
    border-radius: 50%;
    width: 50px;
    height: 50px;
    font-size: 20px;
    cursor: pointer;
    box-shadow: 0 2px 10px rgba(0,0,0,0.3);
    z-index: 1000;
    transition: all 0.3s ease;
}

.scroll-top-btn:hover {
    background-color: #ff6b6b;
    transform: scale(1.1);
}

.hot-token {
    background-color: #006400;
    color: white;
    padding: 5px;
    border-radius: 5px;
}

.very-fast-token {
    background-color: #32CD32;
    color: white;
    padding: 5px;
    border-radius: 5px;
}

.fast-token {
    background-color: #90EE90;
    color: black;
    padding: 5px;
    border-radius: 5px;
}
</style>
""", unsafe_allow_html=True)

scroll_js = """
<script>
function scrollToTop() {
    window.scrollTo({
        top: 0,
        behavior: 'smooth'
    });
}

window.onload = function() {
    if (!document.getElementById('scrollTopBtn')) {
        const btn = document.createElement('button');
        btn.innerHTML = '↑';
        btn.id = 'scrollTopBtn';
        btn.className = 'scroll-top-btn';
        btn.onclick = scrollToTop;
        btn.title = 'Back to top';
        document.body.appendChild(btn);
        
        window.onscroll = function() {
            if (document.body.scrollTop > 100 || document.documentElement.scrollTop > 100) {
                btn.style.display = 'block';
            } else {
                btn.style.display = 'none';
            }
        };
    }
}
</script>
"""

st.markdown(scroll_js, unsafe_allow_html=True)


class TokenAnalyzer:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        """Database connection"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            return True
        except Exception as e:
            st.error(f"Database connection error: {e}")
            return False

    def get_tokens_overview(self):
        """Retrieves an overview of all tokens with key indicators"""
        if not self.conn:
            return pd.DataFrame()

        query = """
        WITH token_stats AS (
            SELECT 
                token_mint,
                COUNT(*) as total_transactions,
                COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as total_buys,
                COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as total_sells,
                COUNT(DISTINCT CASE WHEN transaction_type = 'TransactionType.BUY' THEN wallet_address END) as unique_buyers,
                COUNT(DISTINCT CASE WHEN transaction_type = 'TransactionType.SELL' THEN wallet_address END) as unique_sellers,
                SUM(CASE WHEN transaction_type = 'TransactionType.BUY' THEN amount ELSE 0 END) as buy_volume,
                SUM(CASE WHEN transaction_type = 'TransactionType.SELL' THEN amount ELSE 0 END) as sell_volume,
                AVG(CASE WHEN transaction_type = 'TransactionType.BUY' THEN wallet_priority_at_detection END) as avg_buyer_priority,
                MIN(block_time) as first_tx_timestamp,
                MAX(block_time) as last_tx_timestamp,
                MIN(CASE WHEN transaction_type = 'TransactionType.BUY' THEN created_at END) as first_discovery,
                MIN(timestamp_token_created) as timestamp_token_created,
                COUNT(CASE 
                    WHEN transaction_type = 'TransactionType.BUY' 
                    AND block_time >= (strftime('%s', 'now') - 86400) 
                    THEN 1 
                END) as recent_buys_24h,
                AVG(detection_delay) as avg_detection_delay
            FROM transactions 
            WHERE token_mint IS NOT NULL AND token_mint != ''
            GROUP BY token_mint
            HAVING total_buys > 0
        )
        SELECT 
            token_mint,
            total_buys,
            total_sells,
            unique_buyers,
            unique_sellers,
            buy_volume,
            sell_volume,
            CASE 
                WHEN sell_volume > 0 THEN ROUND(buy_volume / sell_volume, 2)
                ELSE 999.99
            END as volume_ratio,
            ROUND(avg_buyer_priority, 3) as avg_buyer_priority,
            recent_buys_24h,
            ROUND(
                CASE 
                    WHEN total_buys > 0 THEN (recent_buys_24h * 100.0 / total_buys)
                    ELSE 0 
                END, 1
            ) as recent_activity_pct,
            ROUND((strftime('%s', 'now') - COALESCE(timestamp_token_created, first_tx_timestamp)) / 3600.0, 1) as token_age_hours,
            ROUND((first_discovery - COALESCE(timestamp_token_created, first_tx_timestamp)) / 3600.0, 1) as discovery_delay_hours,
            ROUND((last_tx_timestamp - first_tx_timestamp) / 3600.0, 1) as active_lifetime_hours,
            ROUND(avg_detection_delay, 0) as avg_detection_delay_sec
        FROM token_stats
        ORDER BY 
            (CASE WHEN volume_ratio > 10 THEN 10 ELSE volume_ratio END * 20) +
            (unique_buyers * 2) +
            (recent_activity_pct) +
            (avg_buyer_priority * 50) +
            (CASE WHEN discovery_delay_hours <= 2 THEN 30 WHEN discovery_delay_hours <= 6 THEN 20 ELSE 0 END)
            DESC
        """

        return pd.read_sql_query(query, self.conn)

    def calculate_quick_signal(self, row):
        """Calculates a quick signal for overview"""
        score = 0

        # Volume ratio (0-30 points)
        volume_ratio = row['volume_ratio']
        if volume_ratio >= 3:
            score += 30
        elif volume_ratio >= 1.5:
            score += 20
        elif volume_ratio >= 1:
            score += 10

        # Adoption (0-25 points)
        unique_buyers = row['unique_buyers']
        if unique_buyers >= 20:
            score += 25
        elif unique_buyers >= 10:
            score += 15
        elif unique_buyers >= 5:
            score += 10

        # Recent activity (0-20 points)
        recent_activity = row['recent_activity_pct']
        if recent_activity >= 30:
            score += 20
        elif recent_activity >= 15:
            score += 15
        elif recent_activity >= 5:
            score += 10

        # Smart money (0-15 points)
        avg_priority = row['avg_buyer_priority']
        if avg_priority >= 0.7:
            score += 15
        elif avg_priority >= 0.5:
            score += 10
        elif avg_priority >= 0.3:
            score += 5

        # Early discovery (0-10 points)
        discovery_delay = row['discovery_delay_hours']
        if discovery_delay is not None and not pd.isna(discovery_delay):
            if discovery_delay <= 2:
                score += 10
            elif discovery_delay <= 6:
                score += 7
            elif discovery_delay <= 12:
                score += 5

        # Classification
        if score >= 80:
            return "🟢", "STRONG BUY", score, "Strong Buy"
        elif score >= 60:
            return "🟡", "BUY", score, "Buy"
        elif score >= 40:
            return "🟠", "WATCH", score, "Watch"
        else:
            return "🔴", "AVOID", score, "Avoid"

    def calculate_token_indicators(self, token_address):
        """Calculates all indicators for a given token"""
        if not self.conn:
            return None

        base_query = """
        SELECT *, 
            (SELECT timestamp_token_created FROM transactions 
            WHERE token_mint = ? AND timestamp_token_created IS NOT NULL 
            LIMIT 1) as token_creation_timestamp
        FROM transactions 
        WHERE token_mint = ? 
        ORDER BY block_time ASC
        """

        df = pd.read_sql_query(base_query, self.conn, params=[token_address, token_address])

        if len(df) == 0:
            return None

        buys = df[df['transaction_type'] == 'TransactionType.BUY']
        sells = df[df['transaction_type'] == 'TransactionType.SELL']

        indicators = {}

        # Basic indicators
        indicators['unique_buyers'] = len(buys['wallet_address'].unique()) if len(buys) > 0 else 0
        indicators['unique_sellers'] = len(sells['wallet_address'].unique()) if len(sells) > 0 else 0
        indicators['min_buy_amount'] = buys['amount'].min() if len(buys) > 0 else 0
        indicators['max_buy_amount'] = buys['amount'].max() if len(buys) > 0 else 0
        indicators['min_sell_amount'] = sells['amount'].min() if len(sells) > 0 else 0
        indicators['max_sell_amount'] = sells['amount'].max() if len(sells) > 0 else 0
        indicators['total_buys'] = len(buys)
        indicators['total_sells'] = len(sells)
        indicators['buy_volume'] = buys['amount'].sum() if len(buys) > 0 else 0
        indicators['sell_volume'] = sells['amount'].sum() if len(sells) > 0 else 0
        indicators['volume_ratio'] = (indicators['buy_volume'] / indicators['sell_volume']) if indicators['sell_volume'] > 0 else float('inf')

        # Recent activity
        current_timestamp = datetime.now().timestamp()
        yesterday_timestamp = current_timestamp - 86400
        recent_buys = buys[buys['block_time'] >= yesterday_timestamp]
        indicators['recent_buys_24h'] = len(recent_buys)
        indicators['recent_activity_ratio'] = (indicators['recent_buys_24h'] / indicators['total_buys'] * 100) if indicators['total_buys'] > 0 else 0

        # Critical timestamps
        if len(df) > 0:
            indicators['first_tx_timestamp'] = df['block_time'].min()
            indicators['last_tx_timestamp'] = df['block_time'].max()
            first_created_at = df['created_at'].min()
            indicators['first_discovery_timestamp'] = first_created_at
            
            token_creation = df['token_creation_timestamp'].iloc[0]
            indicators['token_creation_timestamp'] = token_creation
            
            base_timestamp = token_creation if token_creation is not None else indicators['first_tx_timestamp']
            indicators['token_age_hours'] = (current_timestamp - base_timestamp) / 3600

            if len(buys) > 0:
                indicators['first_buy_timestamp'] = buys['block_time'].min()
                indicators['hours_token_age_to_first_buy'] = (indicators['first_buy_timestamp'] - indicators['first_tx_timestamp']) / 3600
            else:
                indicators['first_buy_timestamp'] = None
                indicators['hours_token_age_to_first_buy'] = None

            indicators['hours_token_age_to_discovery'] = (indicators['first_discovery_timestamp'] - base_timestamp) / 3600
            indicators['active_lifetime_hours'] = (indicators['last_tx_timestamp'] - indicators['first_tx_timestamp']) / 3600

        # Additional information
        indicators['avg_buy_amount'] = buys['amount'].mean() if len(buys) > 0 else 0
        indicators['avg_sell_amount'] = sells['amount'].mean() if len(sells) > 0 else 0
        indicators['avg_detection_delay'] = df['detection_delay'].mean() if 'detection_delay' in df.columns else 0
        indicators['avg_buyer_priority'] = buys['wallet_priority_at_detection'].mean() if len(buys) > 0 else 0

        # Data for graphs
        indicators['timeline_data'] = df[['block_time', 'transaction_type', 'amount', 'wallet_address']].copy()
        indicators['timeline_data']['datetime'] = pd.to_datetime(indicators['timeline_data']['block_time'], unit='s')

        return indicators

def get_token_age_category(age_hours):
    """Categorizes token age with emoji and priority"""
    if age_hours is None or pd.isna(age_hours):
        return "❓", "Unknown Age", "gray", 0
    
    if age_hours <= 1:  # 1 hour
        return "🔥", "Very Fresh", "red", 4
    elif age_hours <= 6:  # 6 hours
        return "🟠", "Fresh", "orange", 3
    elif age_hours <= 24:  # 24 hours
        return "🟡", "Young", "yellow", 2
    elif age_hours <= 168:  # 7 days
        return "🟢", "Mature", "green", 1
    else:
        return "🔵", "Old", "blue", 0

def get_detection_speed_category(discovery_delay_hours):
    """Categorizes detection speed with emoji and color"""
    if discovery_delay_hours is None or pd.isna(discovery_delay_hours):
        return "❓", "Unknown", "gray", 0
    
    if discovery_delay_hours <= 0.5:  # 30 minutes
        return "🚀", "Ultra-fast", "darkgreen", 4
    elif discovery_delay_hours <= 2:  # 2 hours
        return "⚡", "Very fast", "green", 3
    elif discovery_delay_hours <= 6:  # 6 hours
        return "🟢", "Fast", "lightgreen", 2
    elif discovery_delay_hours <= 24:  # 24 hours
        return "🟡", "Normal", "orange", 1
    else:
        return "🔴", "Late", "red", 0


def format_detection_delay(hours):
    """Formats detection delay with color code"""
    if hours is None or pd.isna(hours):
        return "❓ N/A"
    
    emoji, category, color, priority = get_detection_speed_category(hours)
    
    if hours < 1:
        return f"{emoji} {int(hours * 60)}min"
    elif hours < 24:
        return f"{emoji} {hours:.1f}h"
    else:
        days = int(hours / 24)
        return f"{emoji} {days}d {hours % 24:.1f}h"


def get_data_quality_info(indicators):
    """Returns information about timestamp data quality"""
    if not indicators:
        return "N/A", "❓"
    
    has_real_creation = indicators.get('token_creation_timestamp') is not None
    
    if has_real_creation:
        return "Real timestamp", "✅"
    else:
        return "Estimated (1st tx seen)", "⚠️"


def format_duration(hours):
    """Formats a duration in hours to readable format"""
    if hours is None or pd.isna(hours):
        return "N/A"

    if hours < 1:
        minutes = int(hours * 60)
        return f"{minutes}min"
    elif hours < 24:
        return f"{hours:.1f}h"
    else:
        days = int(hours / 24)
        remaining_hours = hours % 24
        return f"{days}d {remaining_hours:.1f}h"

#------------------------dexscreener-------------------
def update_single_token_data(token_address):
    """Met à jour les données DexScreener pour un token spécifique"""
    try:
        with st.spinner(f"🔄 Updating {token_address[:8]}..."):
            # Éviter le cache pour cette requête - appel direct sans cache
            dex_data = get_dexscreener_data_unified(token_address)
            
            if dex_data:
                st.success(f"✅ Updated {token_address[:8]}...")
                return True
            else:
                st.error(f"❌ Failed to update {token_address[:8]}...")
                return False
                
    except Exception as e:
        st.error(f"❌ Error updating {token_address[:8]}...: {e}")
        return False

def identify_address_type(address: str) -> str:
    """Identifies if the address is a token or pair by analyzing API response"""
    try:
        # Test 1: Try pairs endpoint
        url_pair = f"https://api.dexscreener.com/latest/dex/pairs/solana/{address}"
        response = requests.get(url_pair, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if 'pair' in data and data['pair']:
                return 'pair'
        
        # Test 2: Try tokens endpoint
        url_token = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        response = requests.get(url_token, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if 'pairs' in data and data['pairs']:
                return 'token'
        
        return 'unknown'
        
    except:
        return 'unknown'

def extract_token_from_pair(pair_address: str) -> Optional[str]:
    """Extracts token address from a pair"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/pairs/solana/{pair_address}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if 'pair' in data and data['pair']:
                pair = data['pair']
                
                # Get token addresses from the pair
                base_token = pair.get('baseToken', {}).get('address')
                quote_token = pair.get('quoteToken', {}).get('address')
                
                # Logic to determine which token is the "real" token
                # Generally, we want to avoid stablecoins/SOL as quote tokens
                known_quote_tokens = {
                    'So11111111111111111111111111111111111111112',  # SOL
                    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
                    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
                    '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',  # RAY
                    'mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So'   # mSOL
                }
                
                # If quote_token is known, base_token is probably our token
                if quote_token in known_quote_tokens:
                    return base_token
                # Otherwise, take base_token by default
                else:
                    return base_token
                    
    except Exception as e:
        print(f"Error extracting token from pair {pair_address}: {e}")
        
    return None

@st.cache_data(ttl=300)  # 5 minute cache
def get_dexscreener_data_cached(address: str) -> Optional[Dict]:
    """Cached version to avoid repeated requests"""
    return get_dexscreener_data_unified(address)

def enrich_with_dexscreener_data_smart(df):
    """Optimized version that handles tokens and pairs"""
    if len(df) == 0:
        return df
    
    enriched_df = df.copy()
    
    # Initialize new columns
    for col in ['market_cap', 'price_usd', 'price_change_1h', 'price_change_6h', 
                'price_change_24h', 'volume_24h_dex', 'token_name', 'address_type']:
        enriched_df[col] = None
    
    # Limit to 15 tokens to avoid rate limits
    tokens_to_process = enriched_df.head(15)
    
    with st.spinner(f"🔄 Analyzing and fetching data for {len(tokens_to_process)} addresses..."):
        progress_bar = st.progress(0)
        
        for idx, (index, row) in enumerate(tokens_to_process.iterrows()):
            address = row['token_mint']
            
            # Get data with smart handling
            dex_data = get_dexscreener_data_cached(address)
            
            if dex_data:
                for key in ['market_cap', 'price_usd', 'price_change_1h', 'price_change_6h', 
                           'price_change_24h', 'volume_24h_dex', 'token_name', 'address_type']:
                    enriched_df.loc[index, key] = dex_data.get(key)
                
                # Display detected type
                addr_type = dex_data.get('address_type', 'unknown')
                st.sidebar.text(f"{address[:8]}... → {addr_type}")
            
            progress_bar.progress((idx + 1) / len(tokens_to_process))
            time.sleep(0.3)  # Rate limiting
        
        progress_bar.empty()
    
    return enriched_df

def get_dexscreener_data_unified(address: str) -> Optional[Dict]:
    """Gets DexScreener data automatically handling tokens/pairs"""
    try:
        token_address = address
        
        # Step 1: Identify address type
        address_type = identify_address_type(address)
        
        # Step 2: If it's a pair, extract token address
        if address_type == 'pair':
            print(f"🔄 Pair detected {address[:8]}..., extracting token...")
            token_address = extract_token_from_pair(address)
            
            if not token_address:
                print(f"❌ Unable to extract token from pair {address}")
                return None
            
            print(f"✅ Token extracted: {token_address[:8]}...")
        
        # Step 3: Get data with token address
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if 'pairs' in data and data['pairs']:
                # Filter and sort by liquidity
                valid_pairs = [p for p in data['pairs'] if p.get('fdv') and float(p.get('fdv', 0)) > 0]
                
                if not valid_pairs:
                    return None
                
                # Take pair with most liquidity
                best_pair = sorted(valid_pairs, 
                                 key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0), 
                                 reverse=True)[0]
                
                return {
                    'original_address': address,
                    'token_address': token_address,
                    'address_type': address_type,
                    'market_cap': best_pair.get('fdv'),
                    'price_usd': best_pair.get('priceUsd'),
                    'price_change_1h': best_pair.get('priceChange', {}).get('h1'),
                    'price_change_6h': best_pair.get('priceChange', {}).get('h6'),
                    'price_change_24h': best_pair.get('priceChange', {}).get('h24'),
                    'volume_24h': best_pair.get('volume', {}).get('h24'),
                    'liquidity': best_pair.get('liquidity', {}).get('usd'),
                    'pair_address': best_pair.get('pairAddress'),
                    'dex': best_pair.get('dexId', 'Unknown'),
                    'token_name': best_pair.get('baseToken', {}).get('name'),
                    'token_symbol': best_pair.get('baseToken', {}).get('symbol')
                }
                
        return None
        
    except Exception as e:
        print(f"DexScreener unified error for {address}: {e}")
        return None

def format_market_cap(market_cap):
    """Formats market cap in readable format"""
    if market_cap is None:
        return "N/A"
    
    try:
        mc = float(market_cap)
        if mc >= 1000000000:  # 1B+
            return f"${mc/1000000000:.2f}B"
        elif mc >= 1000000:  # 1M+
            return f"${mc/1000000:.2f}M"
        elif mc >= 1000:  # 1K+
            return f"${mc/1000:.2f}K"
        else:
            return f"${mc:.2f}"
    except:
        return "N/A"

def format_price_change(change):
    """Formats price change with color"""
    if change is None:
        return "N/A"
    
    try:
        change_val = float(change)
        if change_val > 0:
            return f"+{change_val:.2f}%"
        else:
            return f"{change_val:.2f}%"
    except:
        return "N/A"

def get_price_change_emoji(change):
    """Returns emoji based on price change"""
    if change is None:
        return "❓"
    
    try:
        change_val = float(change)
        if change_val > 10:
            return "🚀"
        elif change_val > 5:
            return "📈"
        elif change_val > 0:
            return "🟢"
        elif change_val > -5:
            return "🔴"
        elif change_val > -10:
            return "📉"
        else:
            return "💥"
    except:
        return "❓"

def format_large_number(number):
    """Formats large numbers"""
    if number is None or pd.isna(number):
        return "N/A"

    if number == float('inf'):
        return "∞"
    elif number >= 1000000:
        return f"{number/1000000:.2f}M"
    elif number >= 1000:
        return f"{number/1000:.2f}K"
    else:
        return f"{number:.4f}"


def get_buy_signal(indicators):
    """Calculates a buy signal based on indicators"""
    if not indicators:
        return "❓", "Insufficient data", 0, []

    score = 0
    reasons = []

    # Volume ratio (25 points max)
    volume_ratio = indicators.get('volume_ratio', 0)
    if volume_ratio >= 3:
        score += 25
        reasons.append("✅ Strong accumulation (ratio > 3)")
    elif volume_ratio >= 1.5:
        score += 15
        reasons.append("🟡 Moderate accumulation")
    elif volume_ratio < 0.8:
        score -= 10
        reasons.append("⚠️ More sells than buys")

    # Number of buyer wallets (20 points max)
    unique_buyers = indicators.get('unique_buyers', 0)
    if unique_buyers >= 20:
        score += 20
        reasons.append("✅ Wide adoption (20+ wallets)")
    elif unique_buyers >= 10:
        score += 15
        reasons.append("🟡 Good adoption (10+ wallets)")
    elif unique_buyers < 5:
        score -= 5
        reasons.append("⚠️ Low adoption")

    # Recent activity (20 points max)
    recent_activity = indicators.get('recent_activity_ratio', 0)
    if recent_activity >= 30:
        score += 20
        reasons.append("✅ Very active recently (30%+)")
    elif recent_activity >= 15:
        score += 10
        reasons.append("🟡 Good recent activity")
    elif recent_activity < 5:
        score -= 5
        reasons.append("⚠️ Low recent activity")

    # Buyer quality (20 points max)
    avg_priority = indicators.get('avg_buyer_priority', 0)
    if avg_priority >= 0.7:
        score += 20
        reasons.append("✅ Smart money involved")
    elif avg_priority >= 0.5:
        score += 10
        reasons.append("🟡 Decent buyers")

    # Early discovery (15 points max)
    discovery_delay = indicators.get('hours_token_age_to_discovery', float('inf'))
    if discovery_delay <= 2:
        score += 15
        reasons.append("✅ Very early discovery")
    elif discovery_delay <= 6:
        score += 10
        reasons.append("🟡 Early discovery")
    elif discovery_delay > 24:
        score -= 5
        reasons.append("⚠️ Late discovery")

    # Determine signal
    if score >= 70:
        return "🟢", "STRONG BUY", score, reasons
    elif score >= 50:
        return "🟡", "BUY", score, reasons
    elif score >= 30:
        return "🟠", "HOLD/WATCH", score, reasons
    else:
        return "🔴", "AVOID", score, reasons


def display_hot_tokens_alert(filtered_df):
    """Displays alert for HOT tokens (fast detection + good score)"""
    if len(filtered_df) == 0:
        return
    
    # Create copy to avoid index issues
    hot_df = filtered_df.copy().reset_index(drop=True)
    
    # Add detection categories directly to DataFrame
    hot_df['emoji_detection'] = hot_df['discovery_delay_hours'].apply(
        lambda x: get_detection_speed_category(x)[0]
    )
    hot_df['priority_detection'] = hot_df['discovery_delay_hours'].apply(
        lambda x: get_detection_speed_category(x)[3]
    )
    
    # Tokens detected very fast with good score
    hot_tokens = hot_df[
        (hot_df['priority_detection'] >= 3) &  # Very fast or ultra-fast
        (hot_df['score'] >= 60)      # Decent score
    ].sort_values('discovery_delay_hours')
    
    if len(hot_tokens) > 0:
        st.subheader("🚨 Early Detection Alerts")
        st.success(f"🔥 {len(hot_tokens)} HOT token(s) detected!")
        
        for i, (_, token) in enumerate(hot_tokens.head(3).iterrows()):  # Top 3
            with st.expander(f"🚀 {token['token_mint'][:12]}... - Score: {token['score']}", expanded=i == 0):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Detection", format_detection_delay(token['discovery_delay_hours']))
                    st.metric("Wallets", token['unique_buyers'])
                
                with col2:
                    vol_ratio = "∞" if token['volume_ratio'] >= 999 else f"{token['volume_ratio']:.2f}"
                    st.metric("Volume Ratio", vol_ratio)
                    st.metric("24h Activity", f"{token['recent_activity_pct']:.1f}%")
                
                with col3:
                    st.metric("Priority Score", f"{token['avg_buyer_priority']:.2f}")
                    st.metric("Token Age", format_duration(token['token_age_hours']))
                
                # Quick action
                if st.button(f"🔍 Analyze {token['token_mint'][:8]}...", key=f"hot_{token['token_mint'][:8]}"):
                    st.session_state.selected_token = token['token_mint']
                    st.session_state.view_mode = "🔍 Detailed Analysis"
                    st.rerun()

def generate_token_links(token_mint):
    """Generates DexScreener and Pump.fun links for a token"""
    dexscreener_url = f"https://dexscreener.com/solana/{token_mint}"
    pumpfun_url = f"https://pump.fun/{token_mint}"
    
    # Create clickable links with emojis
    dexscreener_link = f"[📊 DexScreener]({dexscreener_url})"
    pumpfun_link = f"[🚀 Pump.fun]({pumpfun_url})"
    
    return dexscreener_link, pumpfun_link

def display_detection_analysis_chart(overview_df, analyzer):
    """Chart analyzing detection delay vs performance relationship"""
    st.subheader("📈 Detection Delay vs Performance Analysis")
    
    if len(overview_df) == 0:
        st.info("No data available for analysis")
        return
    
    # Calculate scores for all tokens
    scores = []
    for _, row in overview_df.iterrows():
        _, _, score, _ = analyzer.calculate_quick_signal(row)
        scores.append(score)
    
    overview_with_scores = overview_df.copy()
    overview_with_scores['score'] = scores
    
    # Add speed categories
    priorities = []
    for _, row in overview_with_scores.iterrows():
        _, _, _, priority = get_detection_speed_category(row['discovery_delay_hours'])
        priorities.append(priority)
    
    overview_with_scores['priority'] = priorities
    
    # Create scatter plot
    fig = px.scatter(
        overview_with_scores,
        x='discovery_delay_hours',
        y='score',
        size='unique_buyers',
        color='priority',
        hover_data=['token_mint', 'volume_ratio', 'recent_activity_pct'],
        title="Performance vs Detection Delay",
        labels={
            'discovery_delay_hours': 'Detection Delay (hours)',
            'score': 'Performance Score',
            'priority': 'Speed Category'
        },
        color_discrete_map={
            4: 'darkgreen',    # Ultra-fast
            3: 'green',        # Very fast  
            2: 'lightgreen',   # Fast
            1: 'orange',       # Normal
            0: 'red'           # Late
        }
    )
    
    # Add reference lines
    fig.add_hline(y=70, line_dash="dash", line_color="green", 
                  annotation_text="STRONG BUY Threshold (70)")
    fig.add_vline(x=2, line_dash="dash", line_color="blue",
                  annotation_text="Very Fast Threshold (2h)")
    
    # Limit X axis to avoid outliers
    max_x = overview_with_scores['discovery_delay_hours'].max()
    if pd.notna(max_x):
        fig.update_layout(xaxis=dict(range=[0, min(24, max_x)]))
    
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)
    
    # Analysis zone
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**🎯 Optimal Zone** (top left coins)")
        st.write("• Fast detection (< 2h) + High score (> 70)")
        
        optimal_tokens = overview_with_scores[
            (overview_with_scores['discovery_delay_hours'] <= 2) & 
            (overview_with_scores['score'] >= 70)
        ]
        st.metric("Optimal Tokens", len(optimal_tokens))
    
    with col2:
        st.markdown("**📊 Detection/Performance Correlation**")
        if len(overview_with_scores) > 1:
            # Exclude NaN values for correlation
            valid_data = overview_with_scores.dropna(subset=['discovery_delay_hours', 'score'])
            if len(valid_data) > 1:
                correlation = valid_data['discovery_delay_hours'].corr(valid_data['score'])
                st.metric("Correlation", f"{correlation:.3f}")
                
                if correlation < -0.3:
                    st.success("✅ Fast detected tokens perform better")
                elif correlation > 0.3:
                    st.warning("⚠️ Late detected tokens perform better")
                else:
                    st.info("ℹ️ No clear correlation")


def main():
    st.title("🪙 Token Analysis Dashboard - Early Detection")
    st.markdown("---")

    # Sidebar configuration
    st.sidebar.header("Configuration")
    db_path = st.sidebar.text_input(
        "Database path",
        value="solana_wallet_monitor.db",
        help="SQLite file containing the data"
    )

    # Initialize analyzer
    analyzer = TokenAnalyzer(db_path)

    if not analyzer.connect():
        st.stop()

    # Display mode selection
    st.sidebar.header("Display Mode")
    if 'view_mode' not in st.session_state:
        st.session_state.view_mode = "📋 Overview"

    view_mode = st.sidebar.radio(
        "Choose view:",
        ["📋 Overview", "🔍 Detailed Analysis"],
        index=0 if st.session_state.view_mode == "📋 Overview" else 1,
        help="Overview for screening, detailed analysis for specific token"
    )
    st.session_state.view_mode = view_mode

    st.sidebar.header("🔄 Refresh")

    # Manual refresh button (more reliable)
    if st.sidebar.button("🔄 Refresh now", type="primary"):
        st.cache_data.clear()  # Clear cache to force reload
        st.rerun()

    # Last update info
    if 'last_update' not in st.session_state:
        st.session_state.last_update = datetime.now()

    st.sidebar.info(f"⏰ Last update: {st.session_state.last_update.strftime('%H:%M:%S')}")

    # Mark as seen button
    if st.sidebar.button("📝 Mark as seen"):
        st.session_state.last_update = datetime.now()
        st.rerun()

    if view_mode == "📋 Overview":
        # =================== ENHANCED OVERVIEW ===================
        st.header("📋 Token Overview")
        st.markdown("*Quick screening of all tokens to identify early detection opportunities*")

        # Load data
        with st.spinner("🔄 Loading data..."):
            overview_df = analyzer.get_tokens_overview()

        if overview_df.empty:
            st.error("❌ No tokens found in database")
            st.stop()

        # Add detection categories
        overview_df = overview_df.reset_index(drop=True)  # Reset index to avoid duplicates
        
        # Add detection columns directly
        overview_df['emoji_detection'] = overview_df['discovery_delay_hours'].apply(
            lambda x: get_detection_speed_category(x)[0]
        )
        overview_df['category_detection'] = overview_df['discovery_delay_hours'].apply(
            lambda x: get_detection_speed_category(x)[1]
        )
        overview_df['priority'] = overview_df['discovery_delay_hours'].apply(
            lambda x: get_detection_speed_category(x)[3]
        )
        overview_df['emoji_age'] = overview_df['token_age_hours'].apply(
            lambda x: get_token_age_category(x)[0]
        )
        overview_df['category_age'] = overview_df['token_age_hours'].apply(
            lambda x: get_token_age_category(x)[1]
        )
        overview_df['priority_age'] = overview_df['token_age_hours'].apply(
            lambda x: get_token_age_category(x)[3]
        )
        
        # Enhanced filters
        st.subheader("🔧 Screening Filters")
        col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

        with col1:
            min_buyers = st.slider(
                "Min. Buyer Wallets",
                min_value=1,
                max_value=int(overview_df['unique_buyers'].max()),
                value=1
            )

        with col2:
            min_volume_ratio = st.slider(
                "Min. Volume Ratio",
                min_value=0.1,
                max_value=10.0,
                value=0.1,
                step=0.1
            )

        with col3:
            min_recent_activity = st.slider(
                "Min. Recent Activity (%)",
                min_value=0,
                max_value=100,
                value=0
            )

        with col4:
            # Detection speed filter
            detection_speeds = st.multiselect(
                "Detection Speed",
                options=["🚀 Ultra-fast", "⚡ Very fast", "🟢 Fast", "🟡 Normal", "🔴 Late", "❓ Unknown"],
                default=["🚀 Ultra-fast", "⚡ Very fast", "🟢 Fast"],
                help="Filter by detection speed after creation"
            )

        with col5:
            # Token age filter
            age_categories = st.multiselect(
                "Token Age",
                options=["🔥 Very Fresh", "🟠 Fresh", "🟡 Young", "🟢 Mature", "🔵 Old", "❓ Unknown Age"],
                default=["🔥 Very Fresh", "🟠 Fresh", "🟡 Young"],
                help="Filter by token age since creation"
            )

        with col6:
            # Max age backup slider
            max_age_hours = st.slider(
                "Max Age (hours)",
                min_value=1,
                max_value=168,  # 7 days
                value=48,  # 48h default
                help="Maximum age limit (backup)"
            )
            
        with col7:
            min_market_cap = st.selectbox(
                "Min Market Cap",
                options=["All", "$10K+", "$100K+", "$1M+", "$10M+"],
                index=0,
                help="Filter by minimum market cap"
            )

        # Apply filters
        filtered_df = overview_df[
            (overview_df['unique_buyers'] >= min_buyers) &
            (overview_df['volume_ratio'] >= min_volume_ratio) &
            (overview_df['recent_activity_pct'] >= min_recent_activity) &
            (overview_df['token_age_hours'] <= max_age_hours)
        ].copy()

        # Detection speed filter
        if detection_speeds:
            speed_filter = []
            for speed in detection_speeds:
                if "Ultra-fast" in speed:
                    speed_filter.extend(["Ultra-fast"])
                elif "Very fast" in speed:
                    speed_filter.extend(["Very fast"])
                elif "Fast" in speed:
                    speed_filter.extend(["Fast"])
                elif "Normal" in speed:
                    speed_filter.extend(["Normal"])
                elif "Late" in speed:
                    speed_filter.extend(["Late"])
                elif "Unknown" in speed:
                    speed_filter.extend(["Unknown"])
            
            if speed_filter:
                filtered_df = filtered_df[filtered_df['category_detection'].isin(speed_filter)]

        # Age filter
        if age_categories:
            age_filter = []
            for age_cat in age_categories:
                if "Very Fresh" in age_cat:
                    age_filter.extend(["Very Fresh"])
                elif "Fresh" in age_cat:
                    age_filter.extend(["Fresh"])
                elif "Young" in age_cat:
                    age_filter.extend(["Young"])
                elif "Mature" in age_cat:
                    age_filter.extend(["Mature"])
                elif "Old" in age_cat:
                    age_filter.extend(["Old"])
                elif "Unknown Age" in age_cat:
                    age_filter.extend(["Unknown Age"])
            
            if age_filter:
                filtered_df = filtered_df[filtered_df['category_age'].isin(age_filter)]

        # Market cap filter
        if min_market_cap != "All":
            mc_thresholds = {
                "$10K+": 10000,
                "$100K+": 100000, 
                "$1M+": 1000000,
                "$10M+": 10000000
            }
            min_mc = mc_thresholds[min_market_cap]
            filtered_df = filtered_df[
                (filtered_df['market_cap'].notna()) & 
                (filtered_df['market_cap'].astype(float) >= min_mc)
            ]
            
        # Calculate signals
        if len(filtered_df) > 0:
            emoji_list = []
            signal_text_list = []
            signal_list = []
            score_list = []

            for _, row in filtered_df.iterrows():
                emoji, signal_text, score, signal_category = analyzer.calculate_quick_signal(row)
                emoji_list.append(emoji)
                signal_text_list.append(signal_text)
                signal_list.append(signal_category)
                score_list.append(score)

            filtered_df['emoji'] = emoji_list
            filtered_df['signal_text'] = signal_text_list
            filtered_df['signal'] = signal_list
            filtered_df['score'] = score_list
        else:
            filtered_df['emoji'] = []
            filtered_df['signal_text'] = []
            filtered_df['signal'] = []
            filtered_df['score'] = []

        # Early detection metrics
        st.subheader("📊 Statistics - Early Detection & Age")
        col1, col2, col3, col4, col5, col6 = st.columns(6)

        # Calculate detection stats
        ultra_fast = len(overview_df[overview_df['priority'] == 4]) if len(overview_df) > 0 else 0
        very_fast = len(overview_df[overview_df['priority'] == 3]) if len(overview_df) > 0 else 0
        fast = len(overview_df[overview_df['priority'] == 2]) if len(overview_df) > 0 else 0

        very_recent = len(overview_df[overview_df['priority_age'] == 4]) if len(overview_df) > 0 else 0
        recent = len(overview_df[overview_df['priority_age'] == 3]) if len(overview_df) > 0 else 0
        young = len(overview_df[overview_df['priority_age'] == 2]) if len(overview_df) > 0 else 0

        with col1:
            st.metric("🚀 Ultra-fast", ultra_fast, delta="< 30min")
        with col2:
            st.metric("⚡ Very fast", very_fast, delta="< 2h")
        with col3:
            st.metric("🟢 Fast", fast, delta="< 6h")
        with col4:
            if len(overview_df) > 0:
                valid_delays = overview_df['discovery_delay_hours'].dropna()
                avg_detection = valid_delays.mean() if len(valid_delays) > 0 else 0
                st.metric("⏱️ Avg Delay", f"{avg_detection:.1f}h")
            else:
                st.metric("⏱️ Avg Delay", "N/A")
        with col5:
            st.metric("🔥 Very Fresh", very_recent, delta="< 1h")
        with col6:
            early_birds = ultra_fast + very_fast
            fresh_tokens = very_recent + recent
            st.metric("🎯 % Early+Fresh", f"{((early_birds+fresh_tokens)/max(len(overview_df)*2,1)*100):.1f}%")

        # HOT tokens alerts
        display_hot_tokens_alert(filtered_df)

        # Global metrics
        st.subheader("📈 Filtering Results")
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.metric("Total Tokens", len(overview_df))
        with col2:
            st.metric("Filtered Tokens", len(filtered_df))
        with col3:
            if len(filtered_df) > 0:
                strong_buys = len(filtered_df[filtered_df['signal'] == 'Strong Buy'])
            else:
                strong_buys = 0
            st.metric("🟢 STRONG BUY", strong_buys)
        with col4:
            if len(filtered_df) > 0:
                buys = len(filtered_df[filtered_df['signal'] == 'Buy'])
            else:
                buys = 0
            st.metric("🟡 BUY", buys)
        with col5:
            if len(filtered_df) > 0:
                watches = len(filtered_df[filtered_df['signal'] == 'Watch'])
            else:
                watches = 0
            st.metric("🟠 WATCH", watches)

        # Enhanced main table
        st.subheader("🎯 Recommended Tokens - Sorted by Detection Speed")

        if len(filtered_df) > 0:
            # Sort by detection priority then by score
            display_df = enrich_with_dexscreener_data_smart(filtered_df.copy())
            display_df = display_df.sort_values(['priority', 'score'], ascending=[False, False])
            
            # Prepare display data
            display_df['Token'] = display_df['token_mint'].apply(lambda x: f"{x[:8]}...{x[-8:]}")
            display_df['Signal'] = display_df['emoji'] + ' ' + display_df['signal_text']
            display_df['⚡ Detection'] = display_df.apply(
                lambda row: format_detection_delay(row['discovery_delay_hours']), 
                axis=1
            )
            display_df['Volume Ratio'] = display_df['volume_ratio'].apply(
                lambda x: "∞" if x >= 999 else f"{x:.2f}"
            )
            display_df['Age'] = display_df['token_age_hours'].apply(format_duration)
            
            # Add formatted DexScreener data
            display_df['💰 Market Cap'] = display_df['market_cap'].apply(format_market_cap)
            display_df['💲 Price'] = display_df['price_usd'].apply(
                lambda x: f"${float(x):.6f}" if x and float(x) > 0 else "N/A"
            )
            display_df['📈 1h'] = display_df.apply(
                lambda row: get_price_change_emoji(row['price_change_1h']) + " " + format_price_change(row['price_change_1h']),
                axis=1
            )
            display_df['📈 6h'] = display_df.apply(
                lambda row: get_price_change_emoji(row['price_change_6h']) + " " + format_price_change(row['price_change_6h']),
                axis=1
            )
            display_df['📈 24h'] = display_df.apply(
                lambda row: get_price_change_emoji(row['price_change_24h']) + " " + format_price_change(row['price_change_24h']),
                axis=1
            )

            # Add platform links
            display_df['🔗 DexScreener'] = display_df['token_mint'].apply(
                lambda x: f"https://dexscreener.com/solana/{x}"
            )
            display_df['🔗 Pump.fun'] = display_df['token_mint'].apply(
                lambda x: f"https://pump.fun/{x}"
            )

            # Optimized columns for screening
            display_columns = [
                'Token', '⚡ Detection', 'Signal', 'score', '💰 Market Cap', '💲 Price',
                '📈 1h', '📈 6h', '📈 24h', 'unique_buyers', 'Volume Ratio', 'Age', 
                '🔗 DexScreener', '🔗 Pump.fun'
            ]
            
            # Column renaming and configuration
            column_rename = {
                'Token': 'Token',
                '⚡ Detection': '⚡ Detection', 
                'Signal': '📊 Signal',
                'score': 'Score',
                '💰 Market Cap': '💰 MC',
                '💲 Price': '💲 Price',
                '📈 1h': '📈 1h',
                '📈 6h': '📈 6h', 
                '📈 24h': '📈 24h',
                'unique_buyers': 'Wallets',
                'Volume Ratio': 'Vol. Ratio',
                'Age': 'Age',
                '🔗 DexScreener': '📊 DexScreener',
                '🔗 Pump.fun': '🚀 Pump.fun'
            }

            column_config = {
                '📊 DexScreener': st.column_config.LinkColumn(
                    '📊 DexScreener',
                    help="View on DexScreener",
                    width="medium"
                ),
                '🚀 Pump.fun': st.column_config.LinkColumn(
                    '🚀 Pump.fun', 
                    help="View on Pump.fun",
                    width="medium"
                )
            }

            # Display with information
            st.markdown("💡 **Tokens sorted by detection speed then by score**")
            st.markdown("🚀 = Ultra-fast (<30min) | ⚡ = Very fast (<2h) | 🟢 = Fast (<6h)")
            st.markdown("**Token age:** 🔥 = Very Fresh (<1h) | 🟠 = Fresh (<6h) | 🟡 = Young (<24h) | 🟢 = Mature (<7d) | 🔵 = Old (>7d)")

            selected_indices = st.dataframe(
                display_df[display_columns].rename(columns=column_rename),
                use_container_width=True,
                height=400,
                on_select="rerun",
                selection_mode="single-row",
                column_config=column_config
            )
            # AJOUTEZ ICI :
            # Mise à jour sélective des données market
            st.markdown("---")
            st.subheader("🔄 Update Market Data")

            col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                # Sélecteur de token pour update
                tokens_for_update = [(row['token_mint'], f"{row['token_mint'][:8]}... (Score: {row['score']})") 
                                    for _, row in display_df.head(10).iterrows()]
                
                selected_token_for_update = st.selectbox(
                    "Select token to refresh market data:",
                    options=tokens_for_update,
                    format_func=lambda x: x[1],
                    key="token_update_selector"
                )

            with col2:
                if st.button("🔄 Update Selected", type="secondary", use_container_width=True):
                    if selected_token_for_update:
                        token_address = selected_token_for_update[0]
                        
                        # Vider le cache et mettre à jour
                        st.cache_data.clear()
                        success = update_single_token_data(token_address)
                        
                        if success:
                            time.sleep(1)  # Petite pause pour voir le message
                            st.rerun()

            with col3:
                if st.button("🔄 Update Top 5", type="secondary", use_container_width=True):
                    updated_count = 0
                    progress_bar = st.progress(0)
                    
                    for i, (_, row) in enumerate(display_df.head(5).iterrows()):
                        if update_single_token_data(row['token_mint']):
                            updated_count += 1
                        progress_bar.progress((i + 1) / 5)
                        time.sleep(0.5)  # Rate limiting
                    
                    progress_bar.empty()
                    st.success(f"✅ Updated {updated_count}/5 tokens")
                    if updated_count > 0:
                        time.sleep(1)
                        st.rerun()

                        
            # Actions on selection
            if selected_indices.selection.rows:
                selected_idx = selected_indices.selection.rows[0]
                selected_token = display_df.iloc[selected_idx]['token_mint']

                col1, col2, col3 = st.columns(3)

                with col1:
                    if st.button("🔍 Analyze Token", type="primary", key="analyze_btn"):
                        st.session_state.selected_token = selected_token
                        st.session_state.view_mode = "🔍 Detailed Analysis"
                        st.rerun()

                with col2:
                    if st.button("⚡ Quick Analysis", key="quick_btn"):
                        st.session_state.selected_token = selected_token
                        st.session_state.view_mode = "🔍 Detailed Analysis"
                        st.rerun()

                with col3:
                    with st.expander("👁️ Preview"):
                        token_data = display_df.iloc[selected_idx]
                        st.write(f"**Token:** {token_data['token_mint'][:12]}...")
                        
                        st.text_input(
                            "Full address (select to copy):",
                            value=token_data['token_mint'],
                            key=f"addr_{token_data['token_mint'][:8]}",
                            disabled=True
                        )
                        
                        st.write(f"**Signal:** {token_data['emoji']} {token_data['signal_text']}")
                        st.write(f"**Score:** {token_data['score']}/100")
                        st.write(f"**Detection:** {token_data['⚡ Detection']}")
                        st.write(f"**Wallets:** {token_data['unique_buyers']} buyers")
        else:
            st.warning("⚠️ No tokens match the filtering criteria")

        # Enhanced visual analysis
        if len(overview_df) > 0:
            st.subheader("📈 Visual Analysis")

            # Detection/performance correlation chart
            display_detection_analysis_chart(overview_df, analyzer)

            col1, col2 = st.columns(2)

            with col1:
                # Detection speed distribution
                speed_counts = overview_df['category_detection'].value_counts()
                
                fig_speeds = px.pie(
                    values=speed_counts.values,
                    names=speed_counts.index,
                    title="Detection Speed Distribution",
                    color_discrete_map={
                        'Ultra-fast': 'darkgreen',
                        'Very fast': 'green',
                        'Fast': 'lightgreen',
                        'Normal': 'orange',
                        'Late': 'red',
                        'Unknown': 'gray'
                    }
                )
                st.plotly_chart(fig_speeds, use_container_width=True)

            with col2:
                # Signal distribution with detection focus
                if len(filtered_df) > 0:
                    signal_counts = filtered_df['signal'].value_counts()
                    
                    fig_signals = px.bar(
                        x=signal_counts.index,
                        y=signal_counts.values,
                        title="Filtered Token Signals",
                        color=signal_counts.index,
                        color_discrete_map={
                            'Strong Buy': 'green',
                            'Buy': 'yellow',
                            'Watch': 'orange',
                            'Avoid': 'red'
                        }
                    )
                    st.plotly_chart(fig_signals, use_container_width=True)

        # Enhanced export
        st.subheader("📥 Export")
        if len(filtered_df) > 0:
            export_overview = filtered_df[['token_mint', 'signal', 'score', 'unique_buyers',
                                         'volume_ratio', 'recent_activity_pct', 'avg_buyer_priority',
                                         'discovery_delay_hours', 'category_detection', 'token_age_hours']].copy()
            csv_overview = export_overview.to_csv(index=False)

            st.download_button(
                label="📄 Download Overview (CSV)",
                data=csv_overview,
                file_name=f"tokens_overview_detection_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )

    else:
        # =================== DETAILED ANALYSIS ===================

        # Get token list for selector
        tokens_df = analyzer.get_tokens_overview()
        if tokens_df.empty:
            st.error("❌ No tokens found in database")
            st.stop()

        tokens = tokens_df['token_mint'].tolist()

        # Token selection
        st.sidebar.header("Token Selection")

        # Use selected token from overview if available
        default_token = getattr(st.session_state, 'selected_token', tokens[0])
        if default_token not in tokens:
            default_token = tokens[0]

        selected_token = st.sidebar.selectbox(
            "Choose token to analyze:",
            options=tokens,
            index=tokens.index(default_token) if default_token in tokens else 0,
            format_func=lambda x: f"{x[:8]}...{x[-8:]}"
        )

        if not selected_token:
            st.warning("⚠️ Please select a token")
            st.stop()

        # Calculate indicators
        with st.spinner("🔄 Calculating indicators..."):
            indicators = analyzer.calculate_token_indicators(selected_token)

        if not indicators:
            st.error("❌ Unable to calculate indicators for this token")
            st.stop()

        # Display selected token
        st.subheader(f"📊 Detailed Token Analysis")
        st.code(selected_token, language="text")

        # Buy signal
        signal_emoji, signal_text, signal_score, signal_reasons = get_buy_signal(indicators)

        # Display detection speed
        discovery_delay = indicators.get('hours_token_age_to_discovery', None)
        if discovery_delay is not None:
            emoji_detection, category_detection, _, _ = get_detection_speed_category(discovery_delay)
            st.info(f"{emoji_detection} **Detection speed:** {category_detection} ({format_duration(discovery_delay)})")

        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("⬅️ Back to Overview", type="secondary", key="back_btn"):
                st.session_state.view_mode = "📋 Overview"
                st.rerun()
        with col2:
            st.metric(
                f"{signal_emoji} Buy Signal",
                signal_text,
                delta=f"Score: {signal_score}/100"
            )

        # Main metrics
        st.header("📈 Key Indicators")

        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.metric(
                "💰 Buy/Sell Ratio",
                f"{indicators['volume_ratio']:.2f}" if indicators['volume_ratio'] != float('inf') else "∞",
                delta="Volume" if indicators['volume_ratio'] > 1 else "Unfavorable volume"
            )

        with col2:
            st.metric(
                "👥 Buyer Wallets",
                indicators['unique_buyers'],
                delta=f"{indicators['unique_sellers']} sellers"
            )

        with col3:
            st.metric(
                "🔥 Recent Activity",
                f"{indicators['recent_activity_ratio']:.1f}%",
                delta=f"{indicators['recent_buys_24h']} buys/24h"
            )

        with col4:
            st.metric(
                "🧠 Smart Money",
                f"{indicators['avg_buyer_priority']:.2f}",
                delta="Average Priority Score"
            )

        with col5:
            st.metric(
                "⏰ Token Age",
                format_duration(indicators['token_age_hours']),
                delta=format_duration(indicators['active_lifetime_hours']) + " active"
            )

        # Detailed section
        st.header("📊 Detailed Analysis")

        # Tabs
        tab1, tab2, tab3, tab4 = st.tabs(["💹 Trading", "⏰ Temporal", "👥 Wallets", "📈 Charts"])

        with tab1:
            st.subheader("Trading Statistics")

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**🟢 BUYS**")
                st.metric("Transactions", indicators['total_buys'])
                st.metric("Total Volume", f"{format_large_number(indicators['buy_volume'])} SOL")
                st.metric("Average Amount", f"{indicators['avg_buy_amount']:.4f} SOL")
                st.metric("Min - Max", f"{indicators['min_buy_amount']:.4f} - {indicators['max_buy_amount']:.4f} SOL")

            with col2:
                st.markdown("**🔴 SELLS**")
                st.metric("Transactions", indicators['total_sells'])
                st.metric("Total Volume", f"{format_large_number(indicators['sell_volume'])} SOL")
                st.metric("Average Amount", f"{indicators['avg_sell_amount']:.4f} SOL")
                st.metric("Min - Max", f"{indicators['min_sell_amount']:.4f} - {indicators['max_sell_amount']:.4f} SOL")

        with tab2:
            st.subheader("Temporal Analysis")

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**⏰ Key Timestamps**")
                if indicators['first_tx_timestamp']:
                    first_tx_dt = datetime.fromtimestamp(indicators['first_tx_timestamp'])
                    st.write(f"🎯 **First transaction:** {first_tx_dt.strftime('%Y-%m-%d %H:%M:%S')}")

                if indicators['first_buy_timestamp']:
                    first_buy_dt = datetime.fromtimestamp(indicators['first_buy_timestamp'])
                    st.write(f"🛒 **First buy:** {first_buy_dt.strftime('%Y-%m-%d %H:%M:%S')}")

                if indicators['first_discovery_timestamp']:
                    discovery_dt = datetime.fromtimestamp(indicators['first_discovery_timestamp'])
                    st.write(f"🔍 **First discovery:** {discovery_dt.strftime('%Y-%m-%d %H:%M:%S')}")

            with col2:
                st.markdown("**⏱️ Duration Analysis**")
    
                # Data quality information
                quality_info, quality_emoji = get_data_quality_info(indicators)
                st.info(f"{quality_emoji} **Token age based on:** {quality_info}")
                
                st.metric(
                    "Token → First Buy",
                    format_duration(indicators['hours_token_age_to_first_buy']),
                    help="Time between token creation and first detected buy"
                )
                st.metric(
                    "Token → Scanner Discovery", 
                    format_duration(indicators['hours_token_age_to_discovery']),
                    help="Time between token creation and scanner discovery"
                )
                st.metric(
                    "Active Lifetime",
                    format_duration(indicators['active_lifetime_hours']),
                    help="Duration between first and last transaction"
                )

        with tab3:
            st.subheader("Wallet Analysis")

            col1, col2 = st.columns(2)

            with col1:
                # Buyer/seller distribution
                fig_wallets = go.Figure(data=[
                    go.Bar(name='Buyers', x=['Wallets'], y=[indicators['unique_buyers']], marker_color='green'),
                    go.Bar(name='Sellers', x=['Wallets'], y=[indicators['unique_sellers']], marker_color='red')
                ])
                fig_wallets.update_layout(
                    title="Buyers vs Sellers Distribution",
                    barmode='group',
                    height=300
                )
                st.plotly_chart(fig_wallets, use_container_width=True)

            with col2:
                # Advanced metrics
                st.markdown("**🎯 Quality Metrics**")
                st.metric("Average Detection Delay", f"{indicators['avg_detection_delay']:.0f}s")
                st.metric("Average Priority Score", f"{indicators['avg_buyer_priority']:.3f}")

                # Retention ratio (approximation)
                both_buy_sell = min(indicators['unique_buyers'], indicators['unique_sellers'])
                retention_rate = (both_buy_sell / indicators['unique_buyers'] * 100) if indicators['unique_buyers'] > 0 else 0
                st.metric("Approx. Retention Rate", f"{retention_rate:.1f}%")

        with tab4:
            st.subheader("Temporal Evolution")

            if len(indicators['timeline_data']) > 0:
                timeline_df = indicators['timeline_data'].copy()

                # Temporal transaction chart
                timeline_df_plot = timeline_df.copy()
                timeline_df_plot['size_col'] = timeline_df_plot['amount'].abs().clip(lower=0.001)

                fig_timeline = px.scatter(
                    timeline_df_plot,
                    x='datetime',
                    y='amount',
                    color='transaction_type',
                    size='size_col',
                    hover_data=['wallet_address'],
                    title="Transaction Timeline",
                    color_discrete_map={
                        'TransactionType.BUY': 'green',
                        'TransactionType.SELL': 'red'
                    }
                )
                fig_timeline.update_layout(height=400)
                st.plotly_chart(fig_timeline, use_container_width=True)

                # Cumulative volume
                timeline_df_sorted = timeline_df.sort_values('datetime')
                timeline_df_sorted['cumulative_volume'] = timeline_df_sorted['amount'].cumsum()

                fig_cumulative = px.line(
                    timeline_df_sorted,
                    x='datetime',
                    y='cumulative_volume',
                    title="Cumulative Volume Over Time"
                )
                fig_cumulative.update_layout(height=300)
                st.plotly_chart(fig_cumulative, use_container_width=True)
            else:
                st.info("No temporal data available")

        # Enhanced recommendation section
        st.header("🎯 Investment Recommendation")

        col1, col2 = st.columns([2, 1])

        with col1:
            st.subheader(f"{signal_emoji} {signal_text}")

            if signal_reasons:
                st.markdown("**Detailed analysis:**")
                for reason in signal_reasons:
                    st.write(f"• {reason}")

            # Attention points with detection focus
            st.markdown("**⚠️ Points of Attention:**")
            risks = []

            # Detection-specific analysis
            if discovery_delay is not None:
                if discovery_delay > 24:
                    risks.append("Very late discovery (>24h) - missed opportunity")
                elif discovery_delay > 6:
                    risks.append("Late discovery (>6h) - increased competition")

            if indicators['unique_buyers'] < 10:
                risks.append("Limited adoption (few buyer wallets)")
            if indicators['volume_ratio'] < 1:
                risks.append("More sells than buys")
            if indicators['recent_activity_ratio'] < 10:
                risks.append("Low recent activity")
            if indicators['avg_buyer_priority'] < 0.5:
                risks.append("Average buyer quality")

            if risks:
                for risk in risks:
                    st.write(f"• ⚠️ {risk}")
            else:
                st.write("• ✅ No major risks identified")

        with col2:
            st.subheader("📊 Detailed Score")

            # Radar chart of score with detection focus
            categories = ['Volume Ratio', 'Adoption', 'Activity', 'Smart Money', 'Detection Speed']
            
            # Calculate sub-scores (normalized to 100)
            vol_score = min(100, (indicators['volume_ratio'] / 3) * 100) if indicators['volume_ratio'] != float('inf') else 100
            adoption_score = min(100, (indicators['unique_buyers'] / 20) * 100)
            activity_score = min(100, indicators['recent_activity_ratio'] * 3.33)  # 30% = 100
            smart_score = indicators['avg_buyer_priority'] * 100
            
            # Detection speed score
            if discovery_delay is not None:
                if discovery_delay <= 0.5:
                    detection_speed_score = 100
                elif discovery_delay <= 2:
                    detection_speed_score = 80
                elif discovery_delay <= 6:
                    detection_speed_score = 60
                elif discovery_delay <= 24:
                    detection_speed_score = 40
                else:
                    detection_speed_score = 20
            else:
                detection_speed_score = 0

            values = [vol_score, adoption_score, activity_score, smart_score, detection_speed_score]

            fig_radar = go.Figure()
            fig_radar.add_trace(go.Scatterpolar(
                r=values,
                theta=categories,
                fill='toself',
                name='Token Score'
            ))
            fig_radar.update_layout(
                polar=dict(
                    radialaxis=dict(visible=True, range=[0, 100])
                ),
                height=300,
                title="Multi-Dimensional Score"
            )
            st.plotly_chart(fig_radar, use_container_width=True)

        # Enhanced data export
        st.header("📥 Data Export")

        # Prepare data for export with detection info
        export_data = {
            'token_mint': [selected_token],
            'unique_buyers': [indicators['unique_buyers']],
            'unique_sellers': [indicators['unique_sellers']],
            'total_buys': [indicators['total_buys']],
            'total_sells': [indicators['total_sells']],
            'buy_volume': [indicators['buy_volume']],
            'sell_volume': [indicators['sell_volume']],
            'volume_ratio': [indicators['volume_ratio']],
            'recent_activity_pct': [indicators['recent_activity_ratio']],
            'avg_buyer_priority': [indicators['avg_buyer_priority']],
            'token_age_hours': [indicators['token_age_hours']],
            'discovery_delay_hours': [indicators.get('hours_token_age_to_discovery', 0)],
            'detection_speed_category': [category_detection if discovery_delay is not None else "Unknown"],
            'signal_score': [signal_score],
            'signal_text': [signal_text]
        }

        export_df = pd.DataFrame(export_data)
        csv = export_df.to_csv(index=False)

        st.download_button(
            label="📄 Download complete analysis (CSV)",
            data=csv,
            file_name=f"token_analysis_detailed_{selected_token[:8]}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )


if __name__ == "__main__":
    main()