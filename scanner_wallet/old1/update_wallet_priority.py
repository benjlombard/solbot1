# Patch pour corriger l'erreur SQL dans update_wallet_priority
# Remplacer la méthode existante dans scanner_wallet.py

def update_wallet_priority(self, wallet_address: str, scan_duration: float, 
                        discoveries: int, transactions_found: int):
    """Met à jour la priorité d'un wallet après un scan avec logs détaillés - VERSION CORRIGÉE"""
    conn = sqlite3.connect(self.db_name)
    cursor = conn.cursor()
    current_time = int(time.time())
    
    try:
        logger.debug(f"📊 Mise à jour priorité pour {wallet_address[:8]}...")
        
        # Récupérer l'état actuel
        cursor.execute('''
            SELECT priority_score, total_scans, consecutive_empty_scans, 
                activity_score, avg_scan_duration
            FROM wallet_priorities 
            WHERE wallet_address = ?
        ''', (wallet_address,))
        
        current_data = cursor.fetchone()
        if not current_data:
            logger.warning(f"⚠️ Wallet {wallet_address[:8]}... non trouvé dans les priorités")
            return
        
        old_score, total_scans, empty_scans, activity_score, avg_duration = current_data
        
        # Calculer les bonus/malus
        activity_bonus = min(transactions_found * 0.3, 2.0)
        discovery_bonus = min(discoveries * 0.5, 1.5)
        efficiency_penalty = max(0, (scan_duration - 45) * 0.02)
        empty_penalty = min(empty_scans * 0.1, 1.0) if transactions_found == 0 else 0
        
        # Calcul du nouveau score
        if transactions_found > 0 or discoveries > 0:
            new_score = old_score + activity_bonus + discovery_bonus - efficiency_penalty
            new_empty_scans = 0
            logger.debug(f"   📈 ACTIVITÉ DÉTECTÉE")
            logger.debug(f"      Bonus activité: +{activity_bonus:.2f}")
            logger.debug(f"      Bonus découvertes: +{discovery_bonus:.2f}")
            if efficiency_penalty > 0:
                logger.debug(f"      Malus lenteur: -{efficiency_penalty:.2f}")
        else:
            decay_factor = 0.95
            new_score = max(0.5, old_score * decay_factor - empty_penalty)
            new_empty_scans = empty_scans + 1
            logger.debug(f"   📉 SCAN VIDE")
            logger.debug(f"      Facteur de déclin: {decay_factor}")
            logger.debug(f"      Malus scans vides: -{empty_penalty:.2f}")
            logger.debug(f"      Scans vides consécutifs: {new_empty_scans}")
        
        # Limiter le score dans une plage raisonnable
        new_score = max(0.1, min(10.0, new_score))
        
        # Calculer la nouvelle durée moyenne
        if total_scans == 0:
            new_avg_duration = scan_duration
        else:
            new_avg_duration = (avg_duration * total_scans + scan_duration) / (total_scans + 1)
        
        # CORRECTION: Mettre à jour en base sans la colonne inexistante
        cursor.execute('''
            UPDATE wallet_priorities 
            SET 
                last_scan_time = ?,
                total_scans = total_scans + 1,
                avg_scan_duration = ?,
                activity_score = activity_score * 0.8 + ?,
                priority_score = ?,
                consecutive_empty_scans = ?,
                updated_at = ?
            WHERE wallet_address = ?
        ''', (current_time, new_avg_duration, float(transactions_found), 
            new_score, new_empty_scans, current_time, wallet_address))
        
        conn.commit()
        
        # Logs détaillés de la mise à jour
        score_change = new_score - old_score
        change_icon = "📈" if score_change > 0 else "📉" if score_change < 0 else "➡️"
        
        logger.info(f"   {change_icon} Priorité: {old_score:.2f} → {new_score:.2f} ({score_change:+.2f})")
        logger.debug(f"   ⏱️ Durée moyenne: {new_avg_duration:.1f}s")
        logger.debug(f"   📊 Total scans: {total_scans + 1}")
        
        # Déterminer la nouvelle catégorie de priorité
        if new_score >= 4.0:
            category = "🔥 HAUTE (scan toutes les 30s)"
        elif new_score >= 2.0:
            category = "🟡 MOYENNE (scan toutes les 90s)"
        elif new_score >= 1.0:
            category = "🔵 BASSE (scan toutes les 3min)"
        else:
            category = "⚪ TRÈS BASSE (scan toutes les 5min)"
        
        logger.info(f"   📋 Catégorie: {category}")
        
    except sqlite3.Error as e:
        logger.error(f"❌ Erreur mise à jour priorité: {e}")
    except Exception as e:
        logger.error(f"❌ Erreur inattendue mise à jour priorité: {e}")
    finally:
        conn.close()