



-- 6. INSERTION DE DONNÉES INITIALES ET CONFIGURATION
-- =====================================================================

-- Mettre à jour last_historized_at pour les tokens existants
UPDATE tokens 
SET last_historized_at = strftime('%s', 'now') 
WHERE last_historized_at = 0;

-- Initialiser les scores pour les tokens existants
UPDATE tokens 
SET viability_score = 50.0, 
    risk_score = 50.0, 
    momentum_score = 0.0 
WHERE viability_score IS NULL;

-- 7. REQUÊTES DE VÉRIFICATION ET STATISTIQUES
-- =====================================================================

-- Vérifier la structure de la nouvelle table
-- SELECT sql FROM sqlite_master WHERE type='table' AND name='tokens_history';

-- Compter les tokens par statut
-- SELECT 
--     is_dead,
--     COUNT(*) as count,
--     AVG(viability_score) as avg_viability,
--     AVG(risk_score) as avg_risk
-- FROM tokens 
-- GROUP BY is_dead;

-- Statistiques de la table d'historique
-- SELECT 
--     COUNT(*) as total_snapshots,
--     COUNT(DISTINCT token_address) as unique_tokens,
--     MIN(snapshot_timestamp) as oldest_snapshot,
--     MAX(snapshot_timestamp) as newest_snapshot,
--     AVG(viability_score) as avg_viability
-- FROM tokens_history;

-- 8. PROCÉDURES DE MAINTENANCE
-- =====================================================================

-- Nettoyage des anciennes snapshots (garder seulement 30 jours)
-- DELETE FROM tokens_history 
-- WHERE snapshot_timestamp < (strftime('%s', 'now') - 2592000);

-- Recalcul des compteurs de snapshots
-- UPDATE tokens 
-- SET history_snapshots_count = (
--     SELECT COUNT(*) 
--     FROM tokens_history th 
--     WHERE th.token_address = tokens.address
-- );

-- =====================================================================
-- FIN DU SCRIPT - Le schéma est maintenant prêt pour l'historisation
-- =====================================================================