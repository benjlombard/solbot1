import streamlit as st
import pandas as pd
import sqlite3
import subprocess
import sys
from datetime import datetime
import os
from pathlib import Path

# Ajouter la racine du projet au path pour accéder aux modules de config
project_root = Path(__file__).parent.parent.parent.absolute()  # Remonter de 2 niveaux depuis pages/
sys.path.insert(0, str(project_root))

# Import du système de configuration
try:
    from core.config import get_config
    
    # Charger la configuration
    config = get_config()
    DEFAULT_DB_PATH = config.database.get_full_path()
    
    # Afficher un indicateur de succès
    st.success(f"✅ Configuration chargée - DB: {config.database.name}")
    
except ImportError:
    # Fallback si le système de config n'est pas disponible
    DEFAULT_DB_PATH = os.getenv('TRADING_OPPORTUNITIES_DB_PATH', 'database/data/solana_wallet.db')
    st.warning("⚠️ Système de configuration non disponible, utilisation du fallback")
except Exception as e:
    DEFAULT_DB_PATH = 'database/data/solana_wallet.db'
    st.error(f"❌ Erreur chargement config: {e}")

# Configuration de la page
st.set_page_config(
    page_title="💰 Performance des Wallets",
    page_icon="🏆",
    layout="wide",
)

DB_PATH = "solana_wallet_monitor.db"

@st.cache_data(ttl=60)
def get_performance_data():
    """Charge les données de performance depuis la base de données."""
    try:
        conn = sqlite3.connect(DB_PATH)
        # Vérifier si la table existe
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wallets_performance';")
        if cursor.fetchone() is None:
            st.warning("La table 'wallets_performance' n'existe pas. Veuillez lancer l'analyseur au moins une fois.")
            return pd.DataFrame()
            
        df = pd.read_sql_query("SELECT * FROM wallets_performance ORDER BY total_pnl_usd DESC", conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Erreur lors du chargement des données de performance: {e}")
        return pd.DataFrame()

def run_analyzer_script():
    """Exécute le script d'analyse de performance."""
    st.info("Lancement du script d'analyse en arrière-plan...")
    try:
        # Utiliser le même interpréteur Python que celui qui exécute Streamlit
        process = subprocess.Popen([sys.executable, "wallet_performance_analyzer.py"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # Afficher la sortie en temps réel
        with st.expander("Voir la sortie du script"):
            stdout_container = st.empty()
            stderr_container = st.empty()
            
            stdout_log = ""
            stderr_log = ""

            # Lire la sortie ligne par ligne
            for line in iter(process.stdout.readline, ''):
                stdout_log += line
                stdout_container.code(stdout_log, language='log')
            
            for line in iter(process.stderr.readline, ''):
                stderr_log += line
                stderr_container.code(stderr_log, language='log')

        process.wait()
        
        if process.returncode == 0:
            st.success("Le script d'analyse s'est terminé avec succès ! Les données vont être rafraîchies.")
        else:
            st.error(f"Le script d'analyse a échoué avec le code d'erreur {process.returncode}.")
            
        # Vider le cache pour forcer le rechargement des données
        st.cache_data.clear()
        st.rerun()

    except FileNotFoundError:
        st.error("Erreur: Le script 'wallet_performance_analyzer.py' n'a pas été trouvé.")
    except Exception as e:
        st.error(f"Une erreur est survenue lors de l'exécution du script: {e}")


st.title("🏆 Classement des Performances des Wallets")
st.markdown("Analysez la rentabilité des portefeuilles suivis pour identifier le 'Smart Money'.")

if st.button("🚀 Lancer/Actualiser l'Analyse de Performance", type="primary"):
    run_analyzer_script()

st.markdown("---")

df = get_performance_data()

if not df.empty:
    # Métriques globales
    st.subheader("Statistiques Globales")
    total_wallets = len(df)
    profitable_wallets = len(df[df['total_pnl_usd'] > 0])
    total_pnl = df['total_pnl_usd'].sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Wallets Analysés", f"{total_wallets}")
    col2.metric("Wallets Rentables", f"{profitable_wallets} ({(profitable_wallets/total_wallets)*100:.1f}%)")
    col3.metric("P&L Total Cumulé", f"${total_pnl:,.2f}")

    st.subheader("Classement des Wallets")
    
    # Options de tri
    sort_by = st.selectbox(
        "Trier par:",
        ["P&L Total (USD)", "Taux de Réussite (%)", "P&L Réalisé (USD)", "Nombre de Trades"],
    )

    sort_mapping = {
        "P&L Total (USD)": "total_pnl_usd",
        "Taux de Réussite (%)": "win_rate",
        "P&L Réalisé (USD)": "realized_pnl_usd",
        "Nombre de Trades": "total_trades"
    }
    
    df_sorted = df.sort_values(by=sort_mapping[sort_by], ascending=False)

    # Affichage du tableau
    st.dataframe(
        df_sorted.style.format({
            'total_investment_usd': '${:,.2f}',
            'current_portfolio_value_usd': '${:,.2f}',
            'realized_pnl_usd': '${:,.2f}',
            'unrealized_pnl_usd': '${:,.2f}',
            'total_pnl_usd': '${:,.2f}',
            'pnl_percentage': '{:.2f}%',
            'win_rate': '{:.2f}%',
            'last_calculated_at': lambda ts: datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        }).background_gradient(
            cmap='RdYlGn', subset=['total_pnl_usd', 'pnl_percentage', 'win_rate']
        ),
        use_container_width=True
    )
else:
    st.info("Aucune donnée de performance disponible. Lancez l'analyse pour commencer.")
