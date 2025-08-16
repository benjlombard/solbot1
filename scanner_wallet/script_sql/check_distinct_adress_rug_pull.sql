-- Adresses distinctes des tokens avec rug pull détecté
SELECT DISTINCT token_address
FROM tokens_history th1
WHERE th1.liquidity_usd = 0
  AND EXISTS (
      SELECT 1 
      FROM tokens_history th2 
      WHERE th2.token_address = th1.token_address 
        AND th2.snapshot_timestamp < th1.snapshot_timestamp 
        AND th2.liquidity_usd > 1000
  );