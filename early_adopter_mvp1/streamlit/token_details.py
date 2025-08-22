import streamlit as st
import pandas as pd
import json
import sys
import os

from app.database import db

def get_safe(data, key, default):
    """Récupère une valeur d'un dictionnaire de manière sûre, en retournant une valeur par défaut
    si la clé est absente ou si la valeur est None."""
    val = data.get(key)
    return default if val is None else val

def main():
    st.title("🔬 Analyse Détaillée d'un Token")
    
    token_address = st.query_params.get("address")
    
    if not token_address:
        st.error("Adresse du token non spécifiée.")
        return
        
    # Fetch token data
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pump_tokens WHERE address = ?", (token_address,))
        token_row = cursor.fetchone()
        
        cursor.execute("SELECT * FROM rugcheck_reports WHERE token_address = ?", (token_address,))
        rugcheck_row = cursor.fetchone()
        
    if not token_row:
        st.error(f"Token non trouvé: {token_address}")
        return
        
    token_data = dict(token_row)
    rugcheck_report = dict(rugcheck_row) if rugcheck_row else None

    st.header(f"{token_data['name']} ({token_data['symbol']})")
    
    # Liens externes
    st.write(f"""
    **Liens Externes:**
    - [Pump.fun](https://pump.fun/{token_address})
    - [Rugcheck.xyz](https://rugcheck.xyz/tokens/{token_address})
    - [Solscan](https://solscan.io/token/{token_address})
    """)
    
    if rugcheck_report:
        st.subheader("Analyse Rugcheck")
        
        # Afficher les risques
        risks_json = get_safe(rugcheck_report, 'risks', '[]')
        try:
            risks = json.loads(risks_json)
            if risks:
                st.write("**Risques détectés par Rugcheck:**")
                for risk in risks:
                    st.warning(f"- **{risk.get('name', 'Unknown risk')}**: {risk.get('description', '')} (Sévérité: {risk.get('severity', 'N/A')})")
            else:
                st.success("✅ Aucun risque majeur détecté par Rugcheck.")
        except (json.JSONDecodeError, TypeError):
            st.info("Données de risques non disponibles ou invalides.")
        
        st.write("---")
        
        # Afficher les top holders
        top_holders_json = get_safe(rugcheck_report, 'top_holders', '[]')
        try:
            top_holders = json.loads(top_holders_json)
            if top_holders:
                st.write("**Top 10 Holders:**")
                holders_df = pd.DataFrame(top_holders[:10])
                st.dataframe(holders_df, use_container_width=True)
            else:
                st.info("Aucune information sur les détenteurs disponible.")
        except (json.JSONDecodeError, TypeError):
            st.info("Données de détenteurs non disponibles ou invalides.")
    else:
        st.info("Aucun rapport Rugcheck disponible pour ce token.")

if __name__ == "__main__":
    main()
