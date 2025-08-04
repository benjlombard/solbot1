-- =====================================================
-- SCRIPT SQL : AJOUT COLONNES TIMESTAMPS LISIBLES UTC+2
-- Version corrigée sans valeurs par défaut non-constantes
-- =====================================================

-- =====================================================
-- 1. TABLE: transactions
-- =====================================================

-- Ajout des colonnes timestamps lisibles (SANS valeur par défaut non-constante)
ALTER TABLE transactions ADD COLUMN block_time_readable TEXT;
ALTER TABLE transactions ADD COLUMN created_at_readable TEXT;
ALTER TABLE transactions ADD COLUMN updated_at_readable TEXT;

-- Mise à jour des données existantes avec UTC+2
UPDATE transactions 
SET block_time_readable = datetime(block_time, 'unixepoch', '+2 hours')
WHERE block_time IS NOT NULL AND block_time > 0;

UPDATE transactions 
SET created_at_readable = created_at
WHERE created_at IS NOT NULL;

-- Remplir updated_at_readable pour tous les enregistrements existants
UPDATE transactions 
SET updated_at_readable = datetime('now', '+2 hours')
WHERE updated_at_readable IS NULL;

-- Trigger pour block_time_readable lors des INSERT/UPDATE
CREATE TRIGGER IF NOT EXISTS tr_transactions_block_time_readable
AFTER UPDATE OF block_time ON transactions
FOR EACH ROW
WHEN NEW.block_time IS NOT NULL AND NEW.block_time > 0
BEGIN
    UPDATE transactions 
    SET block_time_readable = datetime(NEW.block_time, 'unixepoch', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour block_time_readable lors des INSERT
CREATE TRIGGER IF NOT EXISTS tr_transactions_block_time_insert_readable
AFTER INSERT ON transactions
FOR EACH ROW
WHEN NEW.block_time IS NOT NULL AND NEW.block_time > 0
BEGIN
    UPDATE transactions 
    SET block_time_readable = datetime(NEW.block_time, 'unixepoch', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour created_at_readable lors des INSERT
CREATE TRIGGER IF NOT EXISTS tr_transactions_created_at_readable
AFTER INSERT ON transactions
FOR EACH ROW
BEGIN
    UPDATE transactions 
    SET created_at_readable = COALESCE(NEW.created_at, datetime('now', '+2 hours')),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour updated_at_readable lors des UPDATE
CREATE TRIGGER IF NOT EXISTS tr_transactions_updated_at_readable
AFTER UPDATE ON transactions
FOR EACH ROW
BEGIN
    UPDATE transactions 
    SET updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- =====================================================
-- 2. TABLE: token_accounts
-- =====================================================

-- Ajout des colonnes timestamps lisibles
ALTER TABLE token_accounts ADD COLUMN first_seen_readable TEXT;
ALTER TABLE token_accounts ADD COLUMN last_updated_readable TEXT;
ALTER TABLE token_accounts ADD COLUMN last_scanned_readable TEXT;
ALTER TABLE token_accounts ADD COLUMN created_at_readable TEXT;
ALTER TABLE token_accounts ADD COLUMN updated_at_readable TEXT;

-- Mise à jour des données existantes avec UTC+2
UPDATE token_accounts 
SET first_seen_readable = datetime(first_seen, 'unixepoch', '+2 hours')
WHERE first_seen IS NOT NULL AND first_seen > 0;

UPDATE token_accounts 
SET last_updated_readable = datetime(last_updated, 'unixepoch', '+2 hours')
WHERE last_updated IS NOT NULL AND last_updated > 0;

UPDATE token_accounts 
SET last_scanned_readable = datetime(last_scanned, 'unixepoch', '+2 hours')
WHERE last_scanned IS NOT NULL AND last_scanned > 0;

UPDATE token_accounts 
SET created_at_readable = datetime('now', '+2 hours')
WHERE created_at_readable IS NULL;

UPDATE token_accounts 
SET updated_at_readable = datetime('now', '+2 hours')
WHERE updated_at_readable IS NULL;

-- Trigger pour first_seen_readable lors des INSERT
CREATE TRIGGER IF NOT EXISTS tr_token_accounts_first_seen_readable
AFTER INSERT ON token_accounts
FOR EACH ROW
WHEN NEW.first_seen IS NOT NULL AND NEW.first_seen > 0
BEGIN
    UPDATE token_accounts 
    SET first_seen_readable = datetime(NEW.first_seen, 'unixepoch', '+2 hours'),
        created_at_readable = datetime('now', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour first_seen_readable lors des UPDATE
CREATE TRIGGER IF NOT EXISTS tr_token_accounts_first_seen_update_readable
AFTER UPDATE OF first_seen ON token_accounts
FOR EACH ROW
WHEN NEW.first_seen IS NOT NULL AND NEW.first_seen > 0
BEGIN
    UPDATE token_accounts 
    SET first_seen_readable = datetime(NEW.first_seen, 'unixepoch', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour last_updated_readable lors des UPDATE
CREATE TRIGGER IF NOT EXISTS tr_token_accounts_last_updated_readable
AFTER UPDATE OF last_updated ON token_accounts
FOR EACH ROW
WHEN NEW.last_updated IS NOT NULL AND NEW.last_updated > 0
BEGIN
    UPDATE token_accounts 
    SET last_updated_readable = datetime(NEW.last_updated, 'unixepoch', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour last_scanned_readable lors des UPDATE
CREATE TRIGGER IF NOT EXISTS tr_token_accounts_last_scanned_readable
AFTER UPDATE OF last_scanned ON token_accounts
FOR EACH ROW
WHEN NEW.last_scanned IS NOT NULL AND NEW.last_scanned > 0
BEGIN
    UPDATE token_accounts 
    SET last_scanned_readable = datetime(NEW.last_scanned, 'unixepoch', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour updated_at_readable lors des UPDATE généraux
CREATE TRIGGER IF NOT EXISTS tr_token_accounts_updated_at_readable
AFTER UPDATE ON token_accounts
FOR EACH ROW
BEGIN
    UPDATE token_accounts 
    SET updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- =====================================================
-- 3. TABLE: wallet_priorities
-- =====================================================

-- Ajout des colonnes timestamps lisibles
ALTER TABLE wallet_priorities ADD COLUMN last_scan_time_readable TEXT;
ALTER TABLE wallet_priorities ADD COLUMN last_activity_detected_readable TEXT;
ALTER TABLE wallet_priorities ADD COLUMN created_at_readable TEXT;
ALTER TABLE wallet_priorities ADD COLUMN updated_at_readable TEXT;

-- Mise à jour des données existantes avec UTC+2
UPDATE wallet_priorities 
SET last_scan_time_readable = datetime(last_scan_time, 'unixepoch', '+2 hours')
WHERE last_scan_time IS NOT NULL AND last_scan_time > 0;

UPDATE wallet_priorities 
SET last_activity_detected_readable = datetime(last_activity_detected, 'unixepoch', '+2 hours')
WHERE last_activity_detected IS NOT NULL AND last_activity_detected > 0;

UPDATE wallet_priorities 
SET updated_at_readable = datetime(updated_at, 'unixepoch', '+2 hours')
WHERE updated_at IS NOT NULL AND updated_at > 0;

UPDATE wallet_priorities 
SET created_at_readable = datetime(created_at, 'unixepoch', '+2 hours')
WHERE created_at IS NOT NULL AND created_at > 0;

-- Remplir les valeurs manquantes
UPDATE wallet_priorities 
SET created_at_readable = datetime('now', '+2 hours')
WHERE created_at_readable IS NULL;

UPDATE wallet_priorities 
SET updated_at_readable = datetime('now', '+2 hours')
WHERE updated_at_readable IS NULL;

-- Trigger pour last_scan_time_readable lors des INSERT
CREATE TRIGGER IF NOT EXISTS tr_wallet_priorities_last_scan_readable
AFTER INSERT ON wallet_priorities
FOR EACH ROW
WHEN NEW.last_scan_time IS NOT NULL AND NEW.last_scan_time > 0
BEGIN
    UPDATE wallet_priorities 
    SET last_scan_time_readable = datetime(NEW.last_scan_time, 'unixepoch', '+2 hours'),
        created_at_readable = datetime('now', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour last_scan_time_readable lors des UPDATE
CREATE TRIGGER IF NOT EXISTS tr_wallet_priorities_last_scan_update_readable
AFTER UPDATE OF last_scan_time ON wallet_priorities
FOR EACH ROW
WHEN NEW.last_scan_time IS NOT NULL AND NEW.last_scan_time > 0
BEGIN
    UPDATE wallet_priorities 
    SET last_scan_time_readable = datetime(NEW.last_scan_time, 'unixepoch', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour last_activity_detected_readable lors des UPDATE
CREATE TRIGGER IF NOT EXISTS tr_wallet_priorities_activity_readable
AFTER UPDATE OF last_activity_detected ON wallet_priorities
FOR EACH ROW
WHEN NEW.last_activity_detected IS NOT NULL AND NEW.last_activity_detected > 0
BEGIN
    UPDATE wallet_priorities 
    SET last_activity_detected_readable = datetime(NEW.last_activity_detected, 'unixepoch', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour updated_at_readable lors des UPDATE généraux
CREATE TRIGGER IF NOT EXISTS tr_wallet_priorities_updated_at_readable
AFTER UPDATE ON wallet_priorities
FOR EACH ROW
BEGIN
    UPDATE wallet_priorities 
    SET updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- =====================================================
-- 4. TABLE: scan_history
-- =====================================================

-- Ajout des colonnes timestamps lisibles
ALTER TABLE scan_history ADD COLUMN started_at_readable TEXT;
ALTER TABLE scan_history ADD COLUMN completed_at_readable TEXT;
ALTER TABLE scan_history ADD COLUMN created_at_readable TEXT;
ALTER TABLE scan_history ADD COLUMN updated_at_readable TEXT;

-- Mise à jour des données existantes avec UTC+2
UPDATE scan_history 
SET started_at_readable = datetime(started_at, 'unixepoch', '+2 hours')
WHERE started_at IS NOT NULL AND started_at > 0;

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

-- Trigger pour started_at_readable lors des INSERT
CREATE TRIGGER IF NOT EXISTS tr_scan_history_started_at_readable
AFTER INSERT ON scan_history
FOR EACH ROW
WHEN NEW.started_at IS NOT NULL AND NEW.started_at > 0
BEGIN
    UPDATE scan_history 
    SET started_at_readable = datetime(NEW.started_at, 'unixepoch', '+2 hours'),
        created_at_readable = datetime('now', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour started_at_readable lors des UPDATE
CREATE TRIGGER IF NOT EXISTS tr_scan_history_started_at_update_readable
AFTER UPDATE OF started_at ON scan_history
FOR EACH ROW
WHEN NEW.started_at IS NOT NULL AND NEW.started_at > 0
BEGIN
    UPDATE scan_history 
    SET started_at_readable = datetime(NEW.started_at, 'unixepoch', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour completed_at_readable lors des INSERT
CREATE TRIGGER IF NOT EXISTS tr_scan_history_completed_at_readable
AFTER INSERT ON scan_history
FOR EACH ROW
WHEN NEW.completed_at IS NOT NULL AND NEW.completed_at > 0
BEGIN
    UPDATE scan_history 
    SET completed_at_readable = datetime(NEW.completed_at, 'unixepoch', '+2 hours'),
        created_at_readable = COALESCE(NEW.created_at_readable, datetime('now', '+2 hours')),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour completed_at_readable lors des UPDATE
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

-- Trigger pour updated_at_readable lors des UPDATE généraux
CREATE TRIGGER IF NOT EXISTS tr_scan_history_updated_at_readable
AFTER UPDATE ON scan_history
FOR EACH ROW
BEGIN
    UPDATE scan_history 
    SET updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- =====================================================
-- 5. TABLE: wallet_activity_metrics
-- =====================================================

-- Ajout des colonnes timestamps lisibles
ALTER TABLE wallet_activity_metrics ADD COLUMN timestamp_readable TEXT;
ALTER TABLE wallet_activity_metrics ADD COLUMN created_at_readable TEXT;
ALTER TABLE wallet_activity_metrics ADD COLUMN updated_at_readable TEXT;

-- Mise à jour des données existantes avec UTC+2
UPDATE wallet_activity_metrics 
SET timestamp_readable = datetime(timestamp, 'unixepoch', '+2 hours')
WHERE timestamp IS NOT NULL AND timestamp > 0;

-- Remplir les valeurs manquantes
UPDATE wallet_activity_metrics 
SET created_at_readable = datetime('now', '+2 hours')
WHERE created_at_readable IS NULL;

UPDATE wallet_activity_metrics 
SET updated_at_readable = datetime('now', '+2 hours')
WHERE updated_at_readable IS NULL;

-- Trigger pour timestamp_readable lors des INSERT
CREATE TRIGGER IF NOT EXISTS tr_wallet_activity_metrics_timestamp_readable
AFTER INSERT ON wallet_activity_metrics
FOR EACH ROW
WHEN NEW.timestamp IS NOT NULL AND NEW.timestamp > 0
BEGIN
    UPDATE wallet_activity_metrics 
    SET timestamp_readable = datetime(NEW.timestamp, 'unixepoch', '+2 hours'),
        created_at_readable = datetime('now', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- Trigger pour timestamp_readable lors des UPDATE
CREATE TRIGGER IF NOT EXISTS tr_wallet_activity_metrics_timestamp_update_readable
AFTER UPDATE OF timestamp ON wallet_activity_metrics
FOR EACH ROW
WHEN NEW.timestamp IS NOT NULL AND NEW.timestamp > 0
BEGIN
    UPDATE wallet_activity_metrics 
    SET timestamp_readable = datetime(NEW.timestamp, 'unixepoch', '+2 hours'),
        updated_at_readable = datetime('now', '+2 hours')
    WHERE rowid = NEW.rowid;
END;

-- =====================================================
-- VUES UTILITAIRES UTC+2
-- =====================================================

-- Vue pour transactions avec timestamps lisibles
DROP VIEW IF EXISTS v_transactions_readable;
CREATE VIEW v_transactions_readable AS
SELECT 
    *,
    CASE 
        WHEN block_time_readable IS NOT NULL THEN block_time_readable
        WHEN block_time IS NOT NULL AND block_time > 0 THEN datetime(block_time, 'unixepoch', '+2 hours')
        ELSE 'N/A'
    END as block_time_display,
    CASE 
        WHEN created_at_readable IS NOT NULL THEN created_at_readable
        WHEN created_at IS NOT NULL THEN created_at
        ELSE 'N/A'
    END as created_at_display
FROM transactions;

-- Vue pour token_accounts avec timestamps lisibles
DROP VIEW IF EXISTS v_token_accounts_readable;
CREATE VIEW v_token_accounts_readable AS
SELECT 
    *,
    CASE 
        WHEN first_seen_readable IS NOT NULL THEN first_seen_readable
        WHEN first_seen IS NOT NULL AND first_seen > 0 THEN datetime(first_seen, 'unixepoch', '+2 hours')
        ELSE 'N/A'
    END as first_seen_display,
    CASE 
        WHEN last_scanned_readable IS NOT NULL THEN last_scanned_readable
        WHEN last_scanned IS NOT NULL AND last_scanned > 0 THEN datetime(last_scanned, 'unixepoch', '+2 hours')
        ELSE 'N/A'
    END as last_scanned_display
FROM token_accounts;

-- Vue pour wallet_priorities avec timestamps lisibles
DROP VIEW IF EXISTS v_wallet_priorities_readable;
CREATE VIEW v_wallet_priorities_readable AS
SELECT 
    *,
    CASE 
        WHEN last_scan_time_readable IS NOT NULL THEN last_scan_time_readable
        WHEN last_scan_time IS NOT NULL AND last_scan_time > 0 THEN datetime(last_scan_time, 'unixepoch', '+2 hours')
        ELSE 'N/A'
    END as last_scan_time_display
FROM wallet_priorities;

-- Vue pour scan_history avec timestamps lisibles
DROP VIEW IF EXISTS v_scan_history_readable;
CREATE VIEW v_scan_history_readable AS
SELECT 
    *,
    CASE 
        WHEN started_at_readable IS NOT NULL THEN started_at_readable
        WHEN started_at IS NOT NULL AND started_at > 0 THEN datetime(started_at, 'unixepoch', '+2 hours')
        ELSE 'N/A'
    END as started_at_display,
    CASE 
        WHEN completed_at_readable IS NOT NULL THEN completed_at_readable
        WHEN completed_at IS NOT NULL AND completed_at > 0 THEN datetime(completed_at, 'unixepoch', '+2 hours')
        ELSE 'N/A'
    END as completed_at_display
FROM scan_history;

-- =====================================================
-- REQUÊTES DE VÉRIFICATION UTC+2
-- =====================================================

-- Vérifier l'heure actuelle et UTC+2
SELECT 
    'Heure UTC' as type,
    datetime('now') as timestamp
UNION ALL
SELECT 
    'Heure UTC+2' as type,
    datetime('now', '+2 hours') as timestamp;

-- Vérifier les triggers créés
SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'tr_%' ORDER BY name;

-- Vérifier les colonnes ajoutées
SELECT 'transactions' as table_name, * FROM pragma_table_info('transactions') WHERE name LIKE '%readable';
SELECT 'token_accounts' as table_name, * FROM pragma_table_info('token_accounts') WHERE name LIKE '%readable';
SELECT 'wallet_priorities' as table_name, * FROM pragma_table_info('wallet_priorities') WHERE name LIKE '%readable';
SELECT 'scan_history' as table_name, * FROM pragma_table_info('scan_history') WHERE name LIKE '%readable';

-- Test des timestamps lisibles avec UTC+2
SELECT 
    'transactions' as table_name,
    COUNT(*) as total_rows,
    COUNT(block_time_readable) as with_block_time_readable,
    COUNT(updated_at_readable) as with_updated_at_readable
FROM transactions
UNION ALL
SELECT 
    'scan_history' as table_name,
    COUNT(*) as total_rows,
    COUNT(completed_at_readable) as with_completed_at_readable,
    COUNT(updated_at_readable) as with_updated_at_readable
FROM scan_history
UNION ALL
SELECT 
    'wallet_priorities' as table_name,
    COUNT(*) as total_rows,
    COUNT(last_scan_time_readable) as with_last_scan_readable,
    COUNT(updated_at_readable) as with_updated_at_readable
FROM wallet_priorities;

-- Exemples de données avec heures lisibles
SELECT 
    'Exemple transactions' as source,
    signature,
    block_time,
    block_time_readable,
    updated_at_readable
FROM transactions 
WHERE block_time_readable IS NOT NULL
LIMIT 3;

SELECT 
    'Exemple scan_history' as source,
    scan_type,
    completed_at,
    completed_at_readable,
    updated_at_readable
FROM scan_history 
WHERE completed_at_readable IS NOT NULL
LIMIT 3;

-- =====================================================
-- SCRIPT DE NETTOYAGE (SI BESOIN)
-- =====================================================

/*
-- Pour supprimer tous les triggers si besoin
DROP TRIGGER IF EXISTS tr_transactions_block_time_readable;
DROP TRIGGER IF EXISTS tr_transactions_block_time_insert_readable;
DROP TRIGGER IF EXISTS tr_transactions_created_at_readable;
DROP TRIGGER IF EXISTS tr_transactions_updated_at_readable;

DROP TRIGGER IF EXISTS tr_token_accounts_first_seen_readable;
DROP TRIGGER IF EXISTS tr_token_accounts_first_seen_update_readable;
DROP TRIGGER IF EXISTS tr_token_accounts_last_updated_readable;
DROP TRIGGER IF EXISTS tr_token_accounts_last_scanned_readable;
DROP TRIGGER IF EXISTS tr_token_accounts_updated_at_readable;

DROP TRIGGER IF EXISTS tr_wallet_priorities_last_scan_readable;
DROP TRIGGER IF EXISTS tr_wallet_priorities_last_scan_update_readable;
DROP TRIGGER IF EXISTS tr_wallet_priorities_activity_readable;
DROP TRIGGER IF EXISTS tr_wallet_priorities_updated_at_readable;

DROP TRIGGER IF EXISTS tr_scan_history_started_at_readable;
DROP TRIGGER IF EXISTS tr_scan_history_started_at_update_readable;
DROP TRIGGER IF EXISTS tr_scan_history_completed_at_readable;
DROP TRIGGER IF EXISTS tr_scan_history_completed_at_update_readable;
DROP TRIGGER IF EXISTS tr_scan_history_updated_at_readable;

DROP TRIGGER IF EXISTS tr_wallet_activity_metrics_timestamp_readable;
DROP TRIGGER IF EXISTS tr_wallet_activity_metrics_timestamp_update_readable;

-- Pour supprimer les vues si besoin
DROP VIEW IF EXISTS v_transactions_readable;
DROP VIEW IF EXISTS v_token_accounts_readable;
DROP VIEW IF EXISTS v_wallet_priorities_readable;
DROP VIEW IF EXISTS v_scan_history_readable;

-- Pour supprimer les colonnes readable (attention: SQLite ne supporte pas DROP COLUMN facilement)
-- Il faut recréer les tables sans ces colonnes si nécessaire
*/