# dashboard.py
import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time

# Configuration de la page
st.set_page_config(
    page_title="🎯 Sniper Tracker MVP1", 
    layout="wide",
    initial_sidebar_state="expanded"
)

def main():
    st.title("🎯 Solana Snipers Tracker MVP1")
    st.markdown("---")
    
    # Auto-refresh
    placeholder = st.empty()
    
    with placeholder.container():
        # Métriques rapides en haut
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            tokens_24h = get_tokens_count_24h()
            st.metric("🆕 Tokens (24h)", tokens_24h)
        
        with col2:
            active_snipers = get_active_snipers_count()
            st.metric("🎯 Snipers Actifs", active_snipers)
        
        with col3:
            total_swaps = get_total_swaps_24h()
            st.metric("💫 Swaps (24h)", total_swaps)
        
        with col4:
            avg_reaction = get_avg_reaction_time()
            st.metric("⚡ Temps Moyen", f"{avg_reaction:.2f}s")
        
        st.markdown("---")
        
        # Layout principal
        left_col, right_col = st.columns([2, 1])
        
        with left_col:
            # Tableau des snipers
            st.subheader("🏆 Top Snipers")
            show_snipers_table()
            
            # Activité récente
            st.subheader("📊 Activité Récente")
            show_recent_activity()
        
        with right_col:
            # Nouveaux tokens
            st.subheader("🆕 Nouveaux Tokens")
            show_recent_tokens()
            
            # Stats rapides
            st.subheader("📈 Statistiques")
            show_quick_stats()
    
    # Auto-refresh toutes les 10 secondes
    time.sleep(10)
    st.rerun()

def get_tokens_count_24h():
    conn = sqlite3.connect('snipers.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM tokens 
        WHERE created_at > datetime('now', '-1 day')
    ''')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def show_snipers_table():
    conn = sqlite3.connect('snipers.db')
    
    df = pd.read_sql_query('''
        SELECT 
            SUBSTR(wallet_address, 1, 8) || '...' as Wallet,
            snipe_count as "Snipes",
            ROUND(avg_reaction_time, 2) as "Temps Moy (s)",
            ROUND(confidence_score * 100, 1) as "Score (%)",
            datetime(last_updated, 'localtime') as "Dernière MAJ"
        FROM snipers
        WHERE confidence_score > 0.3
        ORDER BY confidence_score DESC
        LIMIT 15
    ''', conn)
    
    if not df.empty:
        # Coloration basée sur le score
        def color_score(val):
            if val >= 80:
                return 'background-color: #ff4444; color: white'
            elif val >= 60:
                return 'background-color: #ff8800; color: white'
            elif val >= 40:
                return 'background-color: #ffaa00; color: white'
            else:
                return 'background-color: #dddd00; color: black'
        
        styled_df = df.style.applymap(color_score, subset=['Score (%)'])
        st.dataframe(styled_df, use_container_width=True)
    else:
        st.info("Aucun sniper détecté pour le moment")
    
    conn.close()

def show_recent_tokens():
    conn = sqlite3.connect('snipers.db')
    
    df = pd.read_sql_query('''
        SELECT 
            t.symbol,
            SUBSTR(t.address, 1, 6) || '...' as Token,
            COUNT(s.signature) as "Swaps Rapides",
            datetime(t.created_at, 'localtime') as "Créé"
        FROM tokens t
        LEFT JOIN pools p ON t.address = p.token_address
        LEFT JOIN swaps s ON p.address = s.pool_address 
                        AND s.seconds_after_pool_creation < 5.0
        WHERE t.created_at > datetime('now', '-6 hours')
        GROUP BY t.address
        ORDER BY t.created_at DESC
        LIMIT 10
    ''', conn)
    
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Aucun nouveau token récent")
    
    conn.close()

if __name__ == "__main__":
    main()