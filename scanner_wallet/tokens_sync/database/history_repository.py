"""
History Repository
Handles all database operations related to token historical data and snapshots.
"""
import time
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

from .connection import DatabaseConnection, db_retry
from ..models.token_data import TokenData, HistoricalSnapshot


class HistoryRepository:
    """Repository for token historical data operations"""
    
    def __init__(self, db_connection: DatabaseConnection, config, logger: Optional[logging.Logger] = None):
        self.db = db_connection
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
    
    @db_retry(max_retries=3, delay=0.3)
    def create_snapshot(self, token_address: str, token_data: Optional[TokenData] = None) -> bool:
        """
        Create a historical snapshot for a token
        
        Args:
            token_address: Token address to analyze
            token_data: Optional token data, if None will read from tokens table
            
        Returns:
            True if snapshot created successfully
        """
        try:
            with self.db.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # VALIDATION 1: Vérifier si le token existe et a des données valides
                cursor.execute("""
                    SELECT price_usd, market_cap, volume_24h, last_price_update, is_dead, is_rugged
                    FROM tokens 
                    WHERE address = ?
                """, (token_address,))
                
                token_info = cursor.fetchone()
                if not token_info:
                    self.logger.debug(f"Token {token_address[:8]}... not found in database")
                    return False
                
                price_usd, market_cap, volume_24h, last_update, is_dead, is_rugged = token_info
                
                # VALIDATION 2: Skip dead or rugged tokens
                if is_dead or is_rugged:
                    self.logger.debug(f"Token {token_address[:8]}... is dead or rugged, skipping snapshot")
                    return False
                
                # VALIDATION 3: Vérifier que les données sont suffisamment récentes
                current_timestamp = int(time.time())
                if not last_update:
                    self.logger.debug(f"Token {token_address[:8]}... has no recent data")
                    return False
                
                # Vérifier que la dernière mise à jour n'est pas trop ancienne (24h max)
                max_data_age = getattr(self.config, 'max_data_age_for_snapshot_seconds', 86400)
                if current_timestamp - last_update > max_data_age:
                    self.logger.debug(f"Token {token_address[:8]}... data too old ({current_timestamp - last_update}s)")
                    return False
                
                # VALIDATION 4: Vérifier qu'il n'y a pas déjà un snapshot récent
                min_interval = getattr(self.config, 'min_snapshot_interval_seconds', 3600)  # 1 heure par défaut
                cursor.execute("""
                    SELECT snapshot_timestamp FROM tokens_history 
                    WHERE token_address = ? 
                    ORDER BY snapshot_timestamp DESC 
                    LIMIT 1
                """, (token_address,))
                
                last_snapshot = cursor.fetchone()
                if last_snapshot:
                    time_since_last = current_timestamp - last_snapshot[0]
                    if time_since_last < min_interval:
                        self.logger.debug(f"Token {token_address[:8]}... snapshot too recent ({time_since_last}s ago)")
                        return False
                
                # Get previous snapshot ID for linking
                cursor.execute("""
                    SELECT id FROM tokens_history 
                    WHERE token_address = ? 
                    ORDER BY snapshot_timestamp DESC 
                    LIMIT 1
                """, (token_address,))
                last_snapshot_row = cursor.fetchone()
                previous_snapshot_id = last_snapshot_row[0] if last_snapshot_row else None
                
                # Get historical data for calculations
                historical_data = self._get_recent_history(token_address, limit=10)
                
                # Get current token data
                if token_data is None:
                    snapshot_data = self._get_current_token_data(token_address)
                    if not snapshot_data:
                        self.logger.warning(f"No current data found for token {token_address}")
                        return False
                else:
                    snapshot_data = self._convert_token_data_to_snapshot(token_data)
                
                # VALIDATION 5: Valider les données avant insertion
                if not self._validate_snapshot_data(snapshot_data):
                    self.logger.warning(f"Invalid snapshot data for {token_address}")
                    return False
                
                # Calculate deltas from previous snapshot
                deltas = self._calculate_deltas(snapshot_data, historical_data)
                
                # Calculate analysis scores
                scores = self._calculate_analysis_scores(token_address, snapshot_data, historical_data)
                
                # Calculate advanced metrics
                liquidity_mc_ratio = (snapshot_data['liquidity_usd'] / snapshot_data['market_cap']) if snapshot_data['market_cap'] > 0 else 0.0
                volume_mc_ratio = (snapshot_data['volume_24h'] / snapshot_data['market_cap']) if snapshot_data['market_cap'] > 0 else 0.0
                
                # Insert historical snapshot
                # Insert historical snapshot
                cursor.execute("""
                    INSERT INTO tokens_history (
                        token_address,
                        price_usd, market_cap, fdv, liquidity_usd, liquidity_sol, 
                        liquidity_mc_ratio, volume_mc_ratio, price_volatility_1h,
                        volume_5m, volume_1h, volume_6h, volume_24h,
                        price_change_5m, price_change_1h, price_change_6h, price_change_24h,
                        holder_count, bonding_curve_progress,
                        top_holder_percentage, top_10_holders_percentage, 
                        insider_holders_count, insider_networks_detected,
                        lp_providers_count, has_low_liquidity,
                        viability_score, risk_score, momentum_score,
                        rug_risk_score, rug_raw_score, is_rugged, risk_count,
                        creator_address, symbol, name, decimals, logo_uri, 
                        is_verified, metadata_source,
                        snapshot_timestamp, previous_snapshot_id,
                        price_delta_usd, market_cap_delta, volume_24h_delta, 
                        holder_count_delta, rug_risk_score_delta, 
                        top_holder_percentage_delta, insider_holders_delta
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    token_address,
                    snapshot_data.get('price_usd', 0.0), 
                    snapshot_data.get('market_cap', 0.0), 
                    snapshot_data.get('fdv', 0.0),
                    snapshot_data.get('liquidity_usd', 0.0), 
                    snapshot_data.get('liquidity_sol', 0.0),
                    liquidity_mc_ratio, 
                    volume_mc_ratio,
                    snapshot_data.get('price_volatility_1h', 0.0),
                    snapshot_data.get('volume_5m', 0.0), 
                    snapshot_data.get('volume_1h', 0.0), 
                    snapshot_data.get('volume_6h', 0.0), 
                    snapshot_data.get('volume_24h', 0.0),
                    snapshot_data.get('price_change_5m', 0.0), 
                    snapshot_data.get('price_change_1h', 0.0), 
                    snapshot_data.get('price_change_6h', 0.0), 
                    snapshot_data.get('price_change_24h', 0.0),
                    snapshot_data.get('holder_count', 0), 
                    snapshot_data.get('bonding_curve_progress', 0.0),
                    snapshot_data.get('top_holder_percentage', 0.0), 
                    snapshot_data.get('top_10_holders_percentage', 0.0),
                    snapshot_data.get('insider_holders_count', 0), 
                    snapshot_data.get('insider_networks_detected', 0),
                    snapshot_data.get('lp_providers_count', 0), 
                    snapshot_data.get('has_low_liquidity', False),
                    scores.get('viability_score', 50.0), 
                    scores.get('risk_score', 50.0), 
                    scores.get('momentum_score', 0.0),
                    snapshot_data.get('rug_risk_score', 50.0), 
                    snapshot_data.get('rug_raw_score', 0.0),
                    snapshot_data.get('is_rugged', False), 
                    snapshot_data.get('risk_count', 0),
                    snapshot_data.get('creator_address'), 
                    snapshot_data.get('symbol', ''), 
                    snapshot_data.get('name', ''), 
                    snapshot_data.get('decimals', 9), 
                    snapshot_data.get('logo_uri'), 
                    snapshot_data.get('is_verified', False), 
                    snapshot_data.get('metadata_source'),
                    current_timestamp, 
                    previous_snapshot_id,
                    deltas.get('price_delta_usd', 0.0), 
                    deltas.get('market_cap_delta', 0.0), 
                    deltas.get('volume_24h_delta', 0.0), 
                    deltas.get('holder_count_delta', 0),
                    deltas.get('rug_risk_score_delta', 0.0),
                    deltas.get('top_holder_percentage_delta', 0.0),
                    deltas.get('insider_holders_delta', 0)
                ))
                
                # Update tokens table with historization info
                cursor.execute("""
                    UPDATE tokens 
                    SET last_historized_at = ?, 
                        history_snapshots_count = COALESCE(history_snapshots_count, 0) + 1
                    WHERE address = ?
                """, (current_timestamp, token_address))
                
                conn.commit()
                
                self.logger.debug(
                    f"✅ Created snapshot for {token_address[:8]}... "
                    f"(V:{scores.get('viability_score', 0):.1f}, R:{scores.get('risk_score', 0):.1f}, "
                    f"M:{scores.get('momentum_score', 0):.1f})"
                )
                return True
                
        except Exception as e:
            self.logger.error(f"❌ Error creating snapshot for {token_address}: {e}")
            return False

    def _validate_snapshot_data(self, snapshot_data: Dict) -> bool:
        """Validate snapshot data before insertion"""
        try:
            # Vérifications basiques de type et valeur
            if not isinstance(snapshot_data.get('price_usd', 0), (int, float)) or snapshot_data.get('price_usd', 0) < 0:
                self.logger.debug("Invalid price_usd")
                return False
            
            if not isinstance(snapshot_data.get('market_cap', 0), (int, float)) or snapshot_data.get('market_cap', 0) < 0:
                self.logger.debug("Invalid market_cap")
                return False
            
            if not isinstance(snapshot_data.get('volume_24h', 0), (int, float)) or snapshot_data.get('volume_24h', 0) < 0:
                self.logger.debug("Invalid volume_24h")
                return False
            
            if not isinstance(snapshot_data.get('liquidity_usd', 0), (int, float)) or snapshot_data.get('liquidity_usd', 0) < 0:
                self.logger.debug("Invalid liquidity_usd")
                return False
            
            if not isinstance(snapshot_data.get('holder_count', 0), int) or snapshot_data.get('holder_count', 0) < 0:
                self.logger.debug("Invalid holder_count")
                return False
            
            # Vérifications de cohérence
            if snapshot_data.get('market_cap', 0) == 0 and snapshot_data.get('price_usd', 0) > 0:
                self.logger.debug("Inconsistent: price > 0 but market_cap = 0")
                return False
            
            # Vérifier que au moins une métrique importante est présente
            has_meaningful_data = (
                snapshot_data.get('price_usd', 0) > 0 or
                snapshot_data.get('market_cap', 0) > 0 or
                snapshot_data.get('volume_24h', 0) > 0 or
                snapshot_data.get('liquidity_usd', 0) > 0
            )
            
            if not has_meaningful_data:
                self.logger.debug("No meaningful data to snapshot")
                return False
            
            return True
            
        except Exception as e:
            self.logger.debug(f"Error validating snapshot data: {e}")
            return False

    def _get_current_token_data(self, token_address: str) -> Optional[Dict]:
        """Get current token data from tokens table"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tokens WHERE address = ?", (token_address,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            def safe_get(row, column, default=0.0):
                """Safely get value from sqlite3.Row with None handling"""
                try:
                    if column not in row.keys():
                        return default
                    value = row[column]
                    return value if value is not None else default
                except (KeyError, TypeError):
                    return default
            
            return {
                'price_usd': safe_get(row, 'price_usd', 0.0),
                'market_cap': safe_get(row, 'market_cap', 0.0),
                'fdv': safe_get(row, 'fdv', 0.0),
                'liquidity_usd': safe_get(row, 'liquidity_usd', 0.0),
                'liquidity_sol': safe_get(row, 'liquidity_sol', 0.0),
                'volume_5m': safe_get(row, 'volume_5m', 0.0),
                'volume_1h': safe_get(row, 'volume_1h', 0.0),
                'volume_6h': safe_get(row, 'volume_6h', 0.0),
                'volume_24h': safe_get(row, 'volume_24h', 0.0),
                'price_change_5m': safe_get(row, 'price_change_5m', 0.0),
                'price_change_1h': safe_get(row, 'price_change_1h', 0.0),
                'price_change_6h': safe_get(row, 'price_change_6h', 0.0),
                'price_change_24h': safe_get(row, 'price_change_24h', 0.0),
                'price_volatility_1h': safe_get(row, 'price_volatility_1h', 0.0),
                'holder_count': safe_get(row, 'holder_count', 0),
                'bonding_curve_progress': safe_get(row, 'bonding_curve_progress', 0.0),
                'top_holder_percentage': safe_get(row, 'top_holder_percentage', 0.0),
                'top_10_holders_percentage': safe_get(row, 'top_10_holders_percentage', 0.0),
                'insider_holders_count': safe_get(row, 'insider_holders_count', 0),
                'insider_networks_detected': safe_get(row, 'insider_networks_detected', 0),
                'lp_providers_count': safe_get(row, 'lp_providers_count', 0),
                'has_low_liquidity': safe_get(row, 'has_low_liquidity', False),
                'rug_risk_score': safe_get(row, 'rug_risk_score', 50.0),
                'rug_raw_score': safe_get(row, 'rug_raw_score', 0.0),
                'is_rugged': safe_get(row, 'is_rugged', False),
                'risk_count': safe_get(row, 'risk_count', 0),
                'symbol': safe_get(row, 'symbol', ''),
                'name': safe_get(row, 'name', ''),
                'decimals': safe_get(row, 'decimals', 9),
                'creator_address': safe_get(row, 'creator_address', None),
                'logo_uri': safe_get(row, 'logo_uri', None),
                'is_verified': safe_get(row, 'is_verified', False),
                'metadata_source': safe_get(row, 'metadata_source', None)
            }

    def _convert_token_data_to_snapshot(self, token_data: TokenData) -> Dict:
        """Convert TokenData object to snapshot dictionary"""
        return {
            'price_usd': token_data.price_usd,
            'market_cap': token_data.market_cap,
            'fdv': token_data.fdv,
            'liquidity_usd': token_data.liquidity_usd,
            'liquidity_sol': token_data.liquidity_sol,
            'volume_5m': token_data.volume_5m,
            'volume_1h': token_data.volume_1h,
            'volume_6h': token_data.volume_6h,
            'volume_24h': token_data.volume_24h,
            'price_change_5m': token_data.price_change_5m,
            'price_change_1h': token_data.price_change_1h,
            'price_change_6h': token_data.price_change_6h,
            'price_change_24h': token_data.price_change_24h,
            'price_volatility_1h': getattr(token_data, 'price_volatility_1h', 0.0),
            'holder_count': token_data.holder_count,
            'bonding_curve_progress': token_data.bonding_curve_progress,
            'top_holder_percentage': token_data.top_holder_percentage,
            'top_10_holders_percentage': token_data.top_10_holders_percentage,
            'insider_holders_count': token_data.insider_holders_count,
            'insider_networks_detected': token_data.insider_networks_detected,
            'lp_providers_count': token_data.lp_providers_count,
            'has_low_liquidity': token_data.has_low_liquidity,
            'rug_risk_score': token_data.rug_risk_score,
            'rug_raw_score': token_data.rug_raw_score,
            'is_rugged': token_data.is_rugged,
            'risk_count': token_data.risk_count,
            'symbol': token_data.symbol,
            'name': token_data.name,
            'decimals': token_data.decimals,
            'creator_address': token_data.creator_address,
            'logo_uri': token_data.logo_uri,
            'is_verified': token_data.is_verified,
            'metadata_source': token_data.metadata_source
        }

    def _calculate_deltas(self, current_data: Dict, historical_data: List[Dict]) -> Dict:
        """Calculate deltas from previous snapshot"""
        deltas = {
            'price_delta_usd': 0.0,
            'market_cap_delta': 0.0,
            'volume_24h_delta': 0.0,
            'holder_count_delta': 0,
            'rug_risk_score_delta': 0.0,
            'top_holder_percentage_delta': 0.0,
            'insider_holders_delta': 0
        }
        
        if historical_data:
            last_snapshot = historical_data[0]
            deltas['price_delta_usd'] = current_data.get('price_usd', 0) - (last_snapshot.get('price_usd', 0) or 0)
            deltas['market_cap_delta'] = current_data.get('market_cap', 0) - (last_snapshot.get('market_cap', 0) or 0)
            deltas['volume_24h_delta'] = current_data.get('volume_24h', 0) - (last_snapshot.get('volume_24h', 0) or 0)
            deltas['holder_count_delta'] = current_data.get('holder_count', 0) - (last_snapshot.get('holder_count', 0) or 0)
            deltas['rug_risk_score_delta'] = current_data.get('rug_risk_score', 50) - (last_snapshot.get('rug_risk_score', 50) or 50)
            deltas['top_holder_percentage_delta'] = current_data.get('top_holder_percentage', 0) - (last_snapshot.get('top_holder_percentage', 0) or 0)
            deltas['insider_holders_delta'] = current_data.get('insider_holders_count', 0) - (last_snapshot.get('insider_holders_count', 0) or 0)
        
        return deltas

    def _calculate_analysis_scores(self, token_address: str, current_data: Dict, historical_data: List[Dict]) -> Dict:
        """Calculate analysis scores (viability, risk, momentum)"""
        try:
            # Import here to avoid circular imports
            from ..analyzers.token_analyzer import TokenAnalyzer
            
            # Create a temporary TokenData object for scoring
            temp_token_data = TokenData(
                address=token_address,
                symbol=current_data.get('symbol', ''),
                name=current_data.get('name', ''),
                price_usd=current_data.get('price_usd', 0.0),
                market_cap=current_data.get('market_cap', 0.0),
                fdv=current_data.get('fdv', 0.0),
                volume_5m=current_data.get('volume_5m', 0.0),
                volume_1h=current_data.get('volume_1h', 0.0),
                volume_6h=current_data.get('volume_6h', 0.0),
                volume_24h=current_data.get('volume_24h', 0.0),
                price_change_5m=current_data.get('price_change_5m', 0.0),
                price_change_1h=current_data.get('price_change_1h', 0.0),
                price_change_6h=current_data.get('price_change_6h', 0.0),
                price_change_24h=current_data.get('price_change_24h', 0.0),
                holder_count=current_data.get('holder_count', 0),
                liquidity_usd=current_data.get('liquidity_usd', 0.0),
                liquidity_sol=current_data.get('liquidity_sol', 0.0),
                bonding_curve_progress=current_data.get('bonding_curve_progress', 0.0),
                top_holder_percentage=current_data.get('top_holder_percentage', 0.0),
                top_10_holders_percentage=current_data.get('top_10_holders_percentage', 0.0),
                insider_holders_count=current_data.get('insider_holders_count', 0),
                insider_networks_detected=current_data.get('insider_networks_detected', 0),
                lp_providers_count=current_data.get('lp_providers_count', 0),
                has_low_liquidity=current_data.get('has_low_liquidity', False),
                rug_risk_score=current_data.get('rug_risk_score', 50.0),
                rug_raw_score=current_data.get('rug_raw_score', 0.0),
                is_rugged=current_data.get('is_rugged', False),
                risk_count=current_data.get('risk_count', 0)
            )
            
            analyzer = TokenAnalyzer()
            
            viability_score = analyzer.calculate_viability_score(temp_token_data, historical_data)
            risk_score = analyzer.calculate_risk_score(temp_token_data, historical_data)
            momentum_score = analyzer.calculate_momentum_score(temp_token_data, historical_data)
            
            return {
                'viability_score': viability_score,
                'risk_score': risk_score,
                'momentum_score': momentum_score
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating analysis scores: {e}")
            return {
                'viability_score': 50.0,  # Neutral score
                'risk_score': 50.0,      # Neutral score
                'momentum_score': 0.0     # Neutral momentum
            }
    
    # def _get_current_token_data(self, token_address: str) -> Optional[Dict]:
    #     """Get current token data from tokens table"""
    #     with self.db.get_connection_context() as conn:
    #         cursor = conn.cursor()
    #         cursor.execute("SELECT * FROM tokens WHERE address = ?", (token_address,))
    #         row = cursor.fetchone()
            
    #         if not row:
    #             return None
            
    #         def safe_get(row, column, default=0.0):
    #             """Safely get value from sqlite3.Row with None handling"""
    #             try:
    #                 value = row[column] if column in row.keys() else default
    #                 return value if value is not None else default
    #             except (KeyError, TypeError):
    #                 return default
            
    #         return {
    #             'price_usd': safe_get(row, 'price_usd', 0.0),
    #             'market_cap': safe_get(row, 'market_cap', 0.0),
    #             'fdv': safe_get(row, 'fdv', 0.0),
    #             'liquidity_usd': safe_get(row, 'liquidity_usd', 0.0),
    #             'liquidity_sol': safe_get(row, 'liquidity_sol', 0.0),
    #             'liquidity_mc_ratio': safe_get(row, 'liquidity_mc_ratio', 0.0),
    #             'volume_mc_ratio': safe_get(row, 'volume_mc_ratio', 0.0),
    #             'price_volatility_1h': safe_get(row, 'price_volatility_1h', 0.0),
    #             'volume_5m': safe_get(row, 'volume_5m', 0.0),
    #             'volume_1h': safe_get(row, 'volume_1h', 0.0),
    #             'volume_6h': safe_get(row, 'volume_6h', 0.0),
    #             'volume_24h': safe_get(row, 'volume_24h', 0.0),
    #             'price_change_5m': safe_get(row, 'price_change_5m', 0.0),
    #             'price_change_1h': safe_get(row, 'price_change_1h', 0.0),
    #             'price_change_6h': safe_get(row, 'price_change_6h', 0.0),
    #             'price_change_24h': safe_get(row, 'price_change_24h', 0.0),
    #             'holder_count': safe_get(row, 'holder_count', 0),
    #             'bonding_curve_progress': safe_get(row, 'bonding_curve_progress', 0.0),
    #             'top_holder_percentage': safe_get(row, 'top_holder_percentage', 0.0),
    #             'top_10_holders_percentage': safe_get(row, 'top_10_holders_percentage', 0.0),
    #             'insider_holders_count': safe_get(row, 'insider_holders_count', 0),
    #             'insider_networks_detected': safe_get(row, 'insider_networks_detected', 0),
    #             'lp_providers_count': safe_get(row, 'lp_providers_count', 0),
    #             'has_low_liquidity': safe_get(row, 'has_low_liquidity', False),
    #             'rug_risk_score': safe_get(row, 'rug_risk_score', 50),
    #             'rug_raw_score': safe_get(row, 'rug_raw_score', 0),
    #             'is_rugged': safe_get(row, 'is_rugged', False),
    #             'risk_count': safe_get(row, 'risk_count', 0),
    #             'symbol': safe_get(row, 'symbol', ''),
    #             'name': safe_get(row, 'name', ''),
    #             'decimals': safe_get(row, 'decimals', 9),
    #             'creator_address': safe_get(row, 'creator_address', None),
    #             'logo_uri': safe_get(row, 'logo_uri', None),
    #             'is_verified': safe_get(row, 'is_verified', False),
    #             'metadata_source': safe_get(row, 'metadata_source', None)
    #         }
    
    # def _convert_token_data_to_snapshot(self, token_data: TokenData) -> Dict:
    #     """Convert TokenData object to snapshot dictionary"""
    #     return {
    #         'price_usd': token_data.price_usd,
    #         'market_cap': token_data.market_cap,
    #         'fdv': token_data.fdv,
    #         'liquidity_usd': token_data.liquidity_usd,
    #         'liquidity_sol': token_data.liquidity_sol,
    #         'liquidity_mc_ratio': (token_data.liquidity_usd / token_data.market_cap) if token_data.market_cap > 0 else 0.0,
    #         'volume_mc_ratio': (token_data.volume_24h / token_data.market_cap) if token_data.market_cap > 0 else 0.0,
    #         'price_volatility_1h': getattr(token_data, 'price_volatility_1h', 0.0),
    #         'volume_5m': token_data.volume_5m,
    #         'volume_1h': token_data.volume_1h,
    #         'volume_6h': token_data.volume_6h,
    #         'volume_24h': token_data.volume_24h,
    #         'price_change_5m': token_data.price_change_5m,
    #         'price_change_1h': token_data.price_change_1h,
    #         'price_change_6h': token_data.price_change_6h,
    #         'price_change_24h': token_data.price_change_24h,
    #         'holder_count': token_data.holder_count,
    #         'bonding_curve_progress': token_data.bonding_curve_progress,
    #         'top_holder_percentage': token_data.top_holder_percentage,
    #         'top_10_holders_percentage': token_data.top_10_holders_percentage,
    #         'insider_holders_count': token_data.insider_holders_count,
    #         'insider_networks_detected': token_data.insider_networks_detected,
    #         'lp_providers_count': token_data.lp_providers_count,
    #         'has_low_liquidity': token_data.has_low_liquidity,
    #         'rug_risk_score': token_data.rug_risk_score,
    #         'rug_raw_score': token_data.rug_raw_score,
    #         'is_rugged': token_data.is_rugged,
    #         'risk_count': token_data.risk_count,
    #         'symbol': token_data.symbol,
    #         'name': token_data.name,
    #         'decimals': token_data.decimals,
    #         'creator_address': token_data.creator_address,
    #         'logo_uri': token_data.logo_uri,
    #         'is_verified': token_data.is_verified,
    #         'metadata_source': token_data.metadata_source
    #     }
    
    def _calculate_deltas(self, current_data: Dict, historical_data: List[Dict]) -> Dict:
        """Calculate deltas from previous snapshot"""
        deltas = {
            'price_delta_usd': 0.0,
            'market_cap_delta': 0.0,
            'volume_24h_delta': 0.0,
            'holder_count_delta': 0,
            'rug_risk_score_delta': 0.0,
            'top_holder_percentage_delta': 0.0,
            'insider_holders_delta': 0
        }
        
        if historical_data:
            last_snapshot = historical_data[0]
            deltas['price_delta_usd'] = current_data['price_usd'] - (last_snapshot.get('price_usd', 0) or 0)
            deltas['market_cap_delta'] = current_data['market_cap'] - (last_snapshot.get('market_cap', 0) or 0)
            deltas['volume_24h_delta'] = current_data['volume_24h'] - (last_snapshot.get('volume_24h', 0) or 0)
            deltas['holder_count_delta'] = current_data['holder_count'] - (last_snapshot.get('holder_count', 0) or 0)
            deltas['rug_risk_score_delta'] = current_data['rug_risk_score'] - (last_snapshot.get('rug_risk_score', 50) or 50)
            deltas['top_holder_percentage_delta'] = current_data['top_holder_percentage'] - (last_snapshot.get('top_holder_percentage', 0) or 0)
            deltas['insider_holders_delta'] = current_data['insider_holders_count'] - (last_snapshot.get('insider_holders_count', 0) or 0)
        
        return deltas
    
    def _calculate_analysis_scores(self, token_address: str, current_data: Dict, historical_data: List[Dict]) -> Dict:
        """Calculate analysis scores (viability, risk, momentum)"""
        # Import here to avoid circular imports
        from ..analyzers.token_analyzer import TokenAnalyzer
        
        # Create a temporary TokenData object for scoring
        temp_token_data = TokenData(
            address=token_address,
            symbol=current_data['symbol'],
            price_usd=current_data['price_usd'],
            market_cap=current_data['market_cap'],
            fdv=current_data['fdv'],
            volume_5m=current_data['volume_5m'],
            volume_1h=current_data['volume_1h'],
            volume_6h=current_data['volume_6h'],
            volume_24h=current_data['volume_24h'],
            price_change_5m=current_data['price_change_5m'],
            price_change_1h=current_data['price_change_1h'],
            price_change_6h=current_data['price_change_6h'],
            price_change_24h=current_data['price_change_24h'],
            holder_count=current_data['holder_count'],
            liquidity_usd=current_data['liquidity_usd'],
            liquidity_sol=current_data['liquidity_sol'],
            bonding_curve_progress=current_data['bonding_curve_progress']
        )
        
        analyzer = TokenAnalyzer()
        
        return {
            'viability_score': analyzer.calculate_viability_score(temp_token_data, historical_data),
            'risk_score': analyzer.calculate_risk_score(temp_token_data, historical_data),
            'momentum_score': analyzer.calculate_momentum_score(temp_token_data, historical_data)
        }
    
    @db_retry(max_retries=3, delay=0.3)
    def _get_recent_history(self, token_address: str, limit: int = 10) -> List[Dict]:
        """Get recent historical data for a token"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tokens_history 
                WHERE token_address = ? 
                ORDER BY snapshot_timestamp DESC 
                LIMIT ?
            """, (token_address, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    @db_retry(max_retries=3, delay=0.3)
    def get_token_history(
        self, 
        token_address: str, 
        start_time: Optional[int] = None, 
        end_time: Optional[int] = None, 
        limit: int = 100
    ) -> List[Dict]:
        """
        Get historical data for a token within a time range
        
        Args:
            token_address: Token address
            start_time: Start timestamp (Unix)
            end_time: End timestamp (Unix)
            limit: Maximum number of records
            
        Returns:
            List of historical snapshots
        """
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT * FROM tokens_history 
                WHERE token_address = ?
            """
            params = [token_address]
            
            if start_time:
                query += " AND snapshot_timestamp >= ?"
                params.append(start_time)
            
            if end_time:
                query += " AND snapshot_timestamp <= ?"
                params.append(end_time)
            
            query += " ORDER BY snapshot_timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    @db_retry(max_retries=3, delay=0.3)
    def get_history_summary(self, token_address: str) -> Optional[Dict]:
        """Get summary statistics for token history"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_snapshots,
                    MIN(snapshot_timestamp) as first_snapshot,
                    MAX(snapshot_timestamp) as last_snapshot,
                    AVG(viability_score) as avg_viability_score,
                    AVG(risk_score) as avg_risk_score,
                    AVG(momentum_score) as avg_momentum_score,
                    MAX(price_usd) as max_price,
                    MIN(price_usd) as min_price,
                    MAX(market_cap) as max_market_cap,
                    MIN(market_cap) as min_market_cap
                FROM tokens_history 
                WHERE token_address = ?
            """, (token_address,))
            
            row = cursor.fetchone()
            if not row or row['total_snapshots'] == 0:
                return None
            
            return dict(row)
    
    @db_retry(max_retries=3, delay=0.3)
    def get_tokens_needing_historization(self, interval_seconds: int, limit: int = 100) -> List[str]:
        """Get tokens that need historization"""
        cutoff_time = int(time.time()) - interval_seconds
        
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            query = """
            SELECT address 
            FROM tokens 
            WHERE is_dead = 0
            AND (is_rugged = 0 OR is_rugged IS NULL)
            AND (last_historized_at < ? OR last_historized_at IS NULL)
            AND (price_usd > 0 OR market_cap > 0)
            ORDER BY last_historized_at ASC NULLS FIRST
            LIMIT ?
            """
            
            cursor.execute(query, (cutoff_time, limit))
            results = cursor.fetchall()
            
            return [row[0] for row in results]
    
    @db_retry(max_retries=3, delay=0.3)
    def cleanup_old_history(self, days_to_keep: int = 30) -> int:
        """
        Clean up old historical data
        
        Args:
            days_to_keep: Number of days of history to keep
            
        Returns:
            Number of records deleted
        """
        cutoff_timestamp = int(time.time()) - (days_to_keep * 86400)
        
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Delete old snapshots
            cursor.execute("""
                DELETE FROM tokens_history 
                WHERE snapshot_timestamp < ?
            """, (cutoff_timestamp,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            
            self.logger.info(f"🧹 Cleaned up {deleted_count} old history records (older than {days_to_keep} days)")
            
            return deleted_count
    
    @db_retry(max_retries=3, delay=0.3)
    def get_price_history_chart_data(
        self, 
        token_address: str, 
        hours: int = 24,
        interval_minutes: int = 60
    ) -> List[Dict]:
        """
        Get price history data optimized for charting
        
        Args:
            token_address: Token address
            hours: Number of hours of history
            interval_minutes: Minimum interval between data points in minutes
            
        Returns:
            List of price data points
        """
        start_time = int(time.time()) - (hours * 3600)
        interval_seconds = interval_minutes * 60
        
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Get evenly spaced data points
            cursor.execute("""
                WITH numbered_history AS (
                    SELECT 
                        snapshot_timestamp,
                        price_usd,
                        market_cap,
                        volume_24h,
                        ROW_NUMBER() OVER (
                            PARTITION BY (snapshot_timestamp / ?) 
                            ORDER BY snapshot_timestamp DESC
                        ) as rn
                    FROM tokens_history 
                    WHERE token_address = ? 
                    AND snapshot_timestamp >= ?
                )
                SELECT 
                    snapshot_timestamp,
                    price_usd,
                    market_cap,
                    volume_24h
                FROM numbered_history 
                WHERE rn = 1
                ORDER BY snapshot_timestamp ASC
            """, (interval_seconds, token_address, start_time))
            
            return [dict(row) for row in cursor.fetchall()]
    
    @db_retry(max_retries=3, delay=0.3)
    def get_history_statistics(self) -> Dict:
        """Get general statistics about the history table"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Overall statistics
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_snapshots,
                    COUNT(DISTINCT token_address) as unique_tokens,
                    MIN(snapshot_timestamp) as oldest_snapshot,
                    MAX(snapshot_timestamp) as newest_snapshot,
                    AVG(viability_score) as avg_viability_score,
                    AVG(risk_score) as avg_risk_score
                FROM tokens_history
            """)
            
            overall_stats = dict(cursor.fetchone())
            
            # Recent activity (last 24 hours)
            yesterday = int(time.time()) - 86400
            cursor.execute("""
                SELECT 
                    COUNT(*) as snapshots_24h,
                    COUNT(DISTINCT token_address) as tokens_24h
                FROM tokens_history
                WHERE snapshot_timestamp >= ?
            """, (yesterday,))
            
            recent_stats = dict(cursor.fetchone())
            
            # Top tokens by snapshot count
            cursor.execute("""
                SELECT 
                    token_address,
                    COUNT(*) as snapshot_count
                FROM tokens_history
                GROUP BY token_address
                ORDER BY snapshot_count DESC
                LIMIT 10
            """)
            
            top_tokens = [dict(row) for row in cursor.fetchall()]
            
            return {
                'overall': overall_stats,
                'recent_24h': recent_stats,
                'top_tokens_by_snapshots': top_tokens
            }