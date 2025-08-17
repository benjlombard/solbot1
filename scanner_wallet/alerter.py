import time
import sys
import os
from typing import List, Dict, Any

# HACK: Ajouter le répertoire parent au path pour résoudre les imports
# C'est nécessaire car ce script est exécuté comme un script autonome.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from scanner_wallet.core.config import get_config, TokenOpportunityAlertConfig
    from scanner_wallet.core.database import get_database_manager
    from scanner_wallet.core.exceptions import DatabaseError
except ImportError as e:
    print(f"Erreur d'importation: {e}")
    print("Veuillez vous assurer que le script est exécuté depuis la racine du projet ou que scanner_wallet est dans le PYTHONPATH.")
    sys.exit(1)

def check_for_opportunities(db_manager, opp_alert_config: TokenOpportunityAlertConfig) -> List[Dict[str, Any]]:
    """
    Interroge la base de données à la recherche de tokens qui correspondent aux critères d'alerte.
    """
    query = """
        SELECT
            address,
            symbol,
            name,
            price_usd,
            market_cap,
            liquidity_usd,
            viability_score,
            momentum_score,
            risk_score
        FROM
            tokens
        WHERE
            viability_score >= ? AND
            momentum_score >= ? AND
            liquidity_usd >= ? AND
            risk_score <= ? AND
            is_dead = 0 AND
            is_rugged = 0
        ORDER BY
            viability_score DESC, momentum_score DESC
        LIMIT 10;
    """
    params = (
        opp_alert_config.viability_score_min,
        opp_alert_config.momentum_score_min,
        opp_alert_config.liquidity_usd_min,
        opp_alert_config.risk_score_max,
    )

    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Convertir les résultats en dictionnaires pour une utilisation plus facile
            columns = [description[0] for description in cursor.description]
            opportunities = [dict(zip(columns, row)) for row in rows]
            return opportunities
    except DatabaseError as e:
        print(f"Erreur de base de données lors de la recherche d'opportunités: {e}")
        return []
    except Exception as e:
        print(f"Erreur inattendue: {e}")
        return []

def send_alert(token_info: Dict[str, Any]):
    """
    Envoie une alerte pour un token trouvé.
    Pour l'instant, cela imprime dans la console.
    
    Pour une implémentation réelle, vous remplaceriez cette fonction par un appel à une API
    comme Telegram, Discord, ou un service d'email.
    
    Exemple avec Telegram (nécessite la librairie 'python-telegram-bot'):
    --------------------------------------------------------------------
    import telegram
    
    bot = telegram.Bot(token='VOTRE_TOKEN_TELEGRAM')
    chat_id = 'VOTRE_CHAT_ID'
    
    message = f"🚨 Alerte Opportunité! ..."
    
    try:
        bot.send_message(chat_id=chat_id, text=message, parse_mode='MarkdownV2')
    except Exception as e:
        print(f"Erreur envoi Telegram: {e}")
    --------------------------------------------------------------------
    """
    print("="*40)
    print(f"🚨 ALERTE OPPORTUNITÉ DE TRADING 🚨")
    print(f"Token: {token_info.get('name', 'N/A')} ({token_info.get('symbol', 'N/A')})")
    print(f"Adresse: {token_info.get('address')}")
    print(f"-"*20)
    print(f"Prix: ${token_info.get('price_usd', 0):.6f}")
    print(f"Market Cap: ${token_info.get('market_cap', 0):,.0f}")
    print(f"Liquidité: ${token_info.get('liquidity_usd', 0):,.0f}")
    print(f"-"*20)
    print(f"Score de Viabilité: {token_info.get('viability_score', 0):.2f}")
    print(f"Score de Momentum: {token_info.get('momentum_score', 0):.2f}")
    print(f"Score de Risque: {token_info.get('risk_score', 0):.2f}")
    print("="*40)
    print()

def main_loop():
    """
    Boucle principale qui vérifie périodiquement les opportunités.
    """
    try:
        config = get_config()
        db_manager = get_database_manager(config)
    except Exception as e:
        print(f"Erreur critique lors de l'initialisation: {e}")
        sys.exit(1)

    # Utiliser la configuration dédiée
    opp_alert_config = config.alerting.opportunity_alerts

    if not config.alerting.enabled or not opp_alert_config.enabled:
        print("Le système d'alerte global ou d'opportunité est désactivé dans la configuration. Sortie.")
        return

    # Pour éviter d'alerter plusieurs fois pour le même token dans un court intervalle
    recently_alerted = {} # {token_address: timestamp}
    
    print("🚀 Système d'alerte d'opportunités démarré. Vérification des opportunités...")
    while True:
        now = time.time()
        opportunities = check_for_opportunities(db_manager, opp_alert_config)
        
        if opportunities:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {len(opportunities)} opportunité(s) trouvée(s).")
            for opp in opportunities:
                token_address = opp.get('address')
                if token_address in recently_alerted and (now - recently_alerted[token_address]) < opp_alert_config.alert_cooldown_seconds:
                    # Token déjà alerté récemment, on l'ignore
                    continue
                
                send_alert(opp)
                recently_alerted[token_address] = now
        else:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Aucune nouvelle opportunité trouvée.")

        # Nettoyer les anciens tokens de la liste de cooldown
        recently_alerted = {
            addr: ts for addr, ts in recently_alerted.items() 
            if (now - ts) < opp_alert_config.alert_cooldown_seconds
        }
        
        time.sleep(opp_alert_config.check_interval_seconds)

if __name__ == "__main__":
    main_loop()
