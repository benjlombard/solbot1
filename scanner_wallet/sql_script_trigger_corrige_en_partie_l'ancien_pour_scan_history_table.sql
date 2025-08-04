-- =====================================================
-- CORRECTION POUR TABLE: scan_history
-- =====================================================

-- D'abord, supprimer les triggers incorrects
DROP TRIGGER IF EXISTS tr_scan_history_started_at_readable;
DROP TRIGGER IF EXISTS tr_scan_history_started_at_update_readable;
DROP TRIGGER IF EXISTS tr_scan_history_completed_at_readable;
DROP TRIGGER IF EXISTS tr_scan_history_completed_at_update_readable;
DROP TRIGGER IF EXISTS tr_scan_history_updated_at_readable;

-- Supprimer la colonne started_at_readable qui ne sert à rien
-- (SQLite ne supporte pas DROP COLUMN, donc on va l'ignorer)

-- Mise à jour des données existantes avec UTC+2 (SEULEMENT completed_at)
UPDATE scan_history 
SET completed_at_readable = datetime(completed_at, 'unixepoch', '+2 hours')
WHERE completed_at IS NOT NULL AND completed_at > 0;

-- Remplir les valeurs manquantes
UPDATE scan_history 
SET created_at_readable = datetime('now', '+2 hours')
WHERE created_at_readable IS NULL;

UPDATE scan_history 
SET updated_at_readable = datetime('now', '+2 hours')
WHERE updated_at_readable IS NULL;

-- TRIGGER CORRIGÉ pour completed_at_readable lors des INSERT
CREATE TRIGGER IF NOT EXISTS tr_scan_history_completed_at_insert_readable
AFTER INSERT ON scan_history
FOR EACH ROW
WHEN NEW.completed_at IS NOT NULL AND NEW.completed_at > 0
BEGIN
    UPDATE scan_history 
    SET completed_at_readable = datetime(NEW.completed_at, 'unixepoch', '+2 hours'),
        created_at_readable = datetime('now', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- TRIGGER CORRIGÉ pour completed_at_readable lors des UPDATE
CREATE TRIGGER IF NOT EXISTS tr_scan_history_completed_at_update_readable
AFTER UPDATE OF completed_at ON scan_history
FOR EACH ROW
WHEN NEW.completed_at IS NOT NULL AND NEW.completed_at > 0
BEGIN
    UPDATE scan_history 
    SET completed_at_readable = datetime(NEW.completed_at, 'unixepoch', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- TRIGGER CORRIGÉ pour updated_at_readable lors des UPDATE généraux
CREATE TRIGGER IF NOT EXISTS tr_scan_history_general_update_readable
AFTER UPDATE ON scan_history
FOR EACH ROW
BEGIN
    UPDATE scan_history 
    SET updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- TRIGGER CORRIGÉ pour les INSERT sans completed_at
CREATE TRIGGER IF NOT EXISTS tr_scan_history_insert_basic_readable
AFTER INSERT ON scan_history
FOR EACH ROW
WHEN NEW.completed_at IS NULL OR NEW.completed_at = 0
BEGIN
    UPDATE scan_history 
    SET created_at_readable = datetime('now', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Vue corrigée pour scan_history avec timestamps lisibles
DROP VIEW IF EXISTS v_scan_history_readable;
CREATE VIEW v_scan_history_readable AS
SELECT 
    id,
    wallet_address,
    scan_type,
    total_accounts,
    new_accounts,
    scan_duration,
    completed_at,
    CASE 
        WHEN completed_at_readable IS NOT NULL THEN completed_at_readable
        WHEN completed_at IS NOT NULL AND completed_at > 0 THEN datetime(completed_at, 'unixepoch', '+2 hours')
        ELSE 'N/A'
    END as completed_at_display,
    notes,
    priority_score_before,
    priority_score_after,
    rpc_requests_count,
    efficiency_score,
    created_at_readable,
    updated_at_readable
FROM scan_history;

-- =====================================================
-- VÉRIFICATIONS APRÈS CORRECTION
-- =====================================================

-- Vérifier la structure de la table scan_history
SELECT 'Structure scan_history:' as info;
PRAGMA table_info(scan_history);

-- Vérifier les triggers pour scan_history
SELECT 'Triggers scan_history:' as info;
SELECT name FROM sqlite_master 
WHERE type='trigger' 
AND tbl_name='scan_history' 
ORDER BY name;

-- Test d'insertion pour vérifier que les triggers fonctionnent
-- (Vous pouvez exécuter ceci pour tester)
/*
INSERT INTO scan_history 
(wallet_address, scan_type, total_accounts, new_accounts, scan_duration, completed_at, notes)
VALUES 
('TEST_WALLET', 'test', 100, 5, 30.5, strftime('%s', 'now'), 'Test trigger');

-- Vérifier que les colonnes readable ont été remplies
SELECT 
    wallet_address,
    scan_type,
    completed_at,
    completed_at_readable,
    created_at_readable,
    updated_at_readable
FROM scan_history 
WHERE wallet_address = 'TEST_WALLET';

-- Nettoyer le test
DELETE FROM scan_history WHERE wallet_address = 'TEST_WALLET';
*/

-- =====================================================
-- CORRECTION BONUS: Vérifier les autres tables
-- =====================================================

-- Vérifier que toutes les colonnes référencées dans les triggers existent
SELECT 'Vérification colonnes transactions:' as info;
SELECT name FROM pragma_table_info('transactions') WHERE name IN ('block_time', 'created_at');

SELECT 'Vérification colonnes token_accounts:' as info;
SELECT name FROM pragma_table_info('token_accounts') WHERE name IN ('first_seen', 'last_updated', 'last_scanned');

SELECT 'Vérification colonnes wallet_priorities:' as info;
SELECT name FROM pragma_table_info('wallet_priorities') WHERE name IN ('last_scan_time', 'last_activity_detected', 'created_at', 'updated_at');

SELECT 'Vérification colonnes wallet_activity_metrics:' as info;
SELECT name FROM pragma_table_info('wallet_activity_metrics') WHERE name IN ('timestamp');

-- =====================================================
-- TEST FINAL
-- =====================================================

-- Compter les enregistrements avec timestamps lisibles
SELECT 
    'Test final timestamps UTC+2:' as test,
    COUNT(*) as total_scan_history,
    COUNT(completed_at_readable) as with_completed_readable,
    COUNT(created_at_readable) as with_created_readable,
    COUNT(updated_at_readable) as with_updated_readable
FROM scan_history;