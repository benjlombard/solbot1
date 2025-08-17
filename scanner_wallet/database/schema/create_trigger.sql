-- 5. CRÉATION DE TRIGGERS POUR L'AUTOMATISATION
-- =====================================================================

-- Trigger pour mettre à jour automatiquement updated_at dans tokens
CREATE TRIGGER IF NOT EXISTS tokens_updated_at_trigger
    AFTER UPDATE ON tokens
    FOR EACH ROW
BEGIN
    UPDATE tokens SET updated_at = CURRENT_TIMESTAMP WHERE address = NEW.address;
END;

-- Trigger pour incrémenter le compteur de snapshots
CREATE TRIGGER IF NOT EXISTS tokens_history_count_trigger
    AFTER INSERT ON tokens_history
    FOR EACH ROW
BEGIN
    UPDATE tokens 
    SET history_snapshots_count = history_snapshots_count + 1
    WHERE address = NEW.token_address;
END;
